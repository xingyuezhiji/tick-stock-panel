from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.strategy import live
from app.strategy import live_brokers


class FakeStrategy:
    meta = {"id": "s1", "name": "策略一", "limit": 30}


class FakeEngine:
    def has(self, strategy_id: str) -> bool:
        return strategy_id == "s1"

    def get(self, strategy_id: str):
        if strategy_id != "s1":
            raise ValueError(f"unknown strategy: {strategy_id}")
        return FakeStrategy()

    def run(self, strategy_id: str, context, params=None, overrides=None):
        del strategy_id, context, params
        limit = int((overrides or {}).get("display_limit") or 30)
        rows = [
            {"symbol": "000001.SZ", "name": "平安银行", "score": 9.0, "close": 10.0},
            {"symbol": "000002.SZ", "name": "万科A", "score": 8.0, "close": 20.0},
            {"symbol": "000003.SZ", "name": "候选三", "score": 7.0, "close": 30.0},
        ]
        return SimpleNamespace(rows=rows[:limit])


class FakeScreenerService:
    def __init__(self, repo, asset_type="stock"):
        self.repo = repo
        self.asset_type = asset_type

    def latest_date(self):
        return date(2026, 9, 24)

    def build_strategy_context(self, *args, **kwargs):
        return SimpleNamespace()


def _repo(tmp_path):
    return SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))


def _overview():
    return {
        "initialized": True,
        "account_id": "default",
        "holdings": [
            {
                "symbol": "000001.SZ",
                "asset_type": "stock",
                "qty": 100,
                "available_qty": 100,
                "avg_cost": 9.5,
                "last_price": 10.0,
                "pnl": 50.0,
                "pnl_pct": 5.26,
            },
            {
                "symbol": "000099.SZ",
                "asset_type": "stock",
                "qty": 200,
                "available_qty": 200,
                "avg_cost": 5.0,
                "last_price": 4.8,
                "pnl": -40.0,
                "pnl_pct": -4.0,
            },
        ],
    }


def test_brokers_expose_disabled_real_brokers():
    brokers = {row["id"]: row for row in live_brokers.broker_summaries()}
    assert brokers["paper"]["enabled"] is True
    assert brokers["qmt"]["enabled"] is False
    assert brokers["ptrade"]["enabled"] is False


def test_strategy_pool_marks_holdings_outside_buffer(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "ScreenerService", FakeScreenerService)
    monkeypatch.setattr(live.strategy_config, "load_override", lambda data_dir, strategy_id: {})
    monkeypatch.setattr(live.paper, "overview", lambda data_dir, account_id="default": _overview())

    pool = live.build_strategy_pool(
        _repo(tmp_path),
        FakeEngine(),
        strategy_id="s1",
        account_id="default",
        as_of=date(2026, 9, 24),
        top_n=1,
        buffer_n=2,
    )

    assert [row["symbol"] for row in pool["candidates"]] == ["000001.SZ"]
    holdings = {row["symbol"]: row for row in pool["holdings"]}
    assert holdings["000001.SZ"]["in_buffer"] is True
    assert holdings["000099.SZ"]["in_buffer"] is False
    assert holdings["000099.SZ"]["suggested_action"] == "sell"


def test_buy_selected_skips_held_and_outside_pool(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "ScreenerService", FakeScreenerService)
    monkeypatch.setattr(live.strategy_config, "load_override", lambda data_dir, strategy_id: {})
    monkeypatch.setattr(live.paper, "overview", lambda data_dir, account_id="default": _overview())
    created_orders = []

    def fake_create_order(data_dir, symbol, side, **kwargs):
        order = {"id": f"ord_{symbol}", "symbol": symbol, "side": side, **kwargs}
        created_orders.append(order)
        return order, None

    monkeypatch.setattr(live.paper, "create_order", fake_create_order)

    result = live.buy_selected(
        tmp_path,
        _repo(tmp_path),
        FakeEngine(),
        {
            "strategy_id": "s1",
            "symbols": ["000001.SZ", "000002.SZ", "000099.SZ"],
            "account": "default",
            "broker": "paper",
            "top_n": 2,
            "buffer_n": 2,
            "amount_per_symbol": 10000,
            "order_type": "next_open",
        },
    )

    assert [row["symbol"] for row in result["created"]] == ["000002.SZ"]
    assert {row["symbol"]: row["reason"] for row in result["skipped"]} == {
        "000001.SZ": "already_held",
        "000099.SZ": "not_in_buy_pool",
    }
    assert created_orders[0]["source"] == "live"


def test_sell_out_of_buffer_skips_buffer_members(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "ScreenerService", FakeScreenerService)
    monkeypatch.setattr(live.strategy_config, "load_override", lambda data_dir, strategy_id: {})
    monkeypatch.setattr(live.paper, "overview", lambda data_dir, account_id="default": _overview())

    def fake_create_order(data_dir, symbol, side, **kwargs):
        return {"id": f"ord_{symbol}", "symbol": symbol, "side": side, **kwargs}, None

    monkeypatch.setattr(live.paper, "create_order", fake_create_order)

    result = live.sell_out_of_buffer(
        tmp_path,
        _repo(tmp_path),
        FakeEngine(),
        {
            "strategy_id": "s1",
            "symbols": ["000001.SZ", "000099.SZ"],
            "account": "default",
            "broker": "paper",
            "top_n": 1,
            "buffer_n": 2,
            "order_type": "next_open",
        },
    )

    assert [row["symbol"] for row in result["created"]] == ["000099.SZ"]
    assert result["created"][0]["qty"] == 200
    assert result["skipped"] == [
        {"symbol": "000001.SZ", "reason": "still_in_buffer", "message": "仍在缓冲候选池"}
    ]


def test_disabled_broker_does_not_create_orders(tmp_path):
    result = live.buy_selected(
        tmp_path,
        _repo(tmp_path),
        FakeEngine(),
        {"strategy_id": "s1", "symbols": ["000002.SZ"], "broker": "qmt"},
    )

    assert result["created"] == []
    assert result["skipped"][0]["reason"] == "broker_disabled"
    assert "QMT broker 未配置" in result["errors"][0]["message"]
