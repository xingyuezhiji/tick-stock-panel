from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from app.strategy import live
from app.strategy import live_brokers


class FakeStrategy:
    meta = {"id": "s1", "name": "策略一", "limit": 30}
    max_hold_days = 3


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


def _positions():
    return {
        "000001.SZ": {"symbol": "000001.SZ", "lots": [{"date": "2026-09-23", "qty": 100}]},
        "000099.SZ": {"symbol": "000099.SZ", "lots": [{"date": "2026-09-20", "qty": 200}]},
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
    monkeypatch.setattr(live.paper, "load_positions", lambda data_dir, account_id="default": _positions())

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
    assert holdings["000099.SZ"]["cycle_sellable"] is True
    assert holdings["000099.SZ"]["cycle_sell_qty"] == 200
    assert holdings["000099.SZ"]["suggested_action"] == "sell"


def test_qmt_order_plan_builds_preview_orders(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "ScreenerService", FakeScreenerService)
    monkeypatch.setattr(live.strategy_config, "load_override", lambda data_dir, strategy_id: {})
    monkeypatch.setattr(live.paper, "overview", lambda data_dir, account_id="default": _overview())
    monkeypatch.setattr(live.paper, "load_positions", lambda data_dir, account_id="default": _positions())

    plan = live.build_qmt_order_plan(
        _repo(tmp_path),
        FakeEngine(),
        strategy_id="s1",
        account_id="default",
        as_of=date(2026, 9, 24),
        top_n=2,
        buffer_n=2,
        amount_per_symbol=10000,
    )

    assert plan["mode"] == "preview"
    assert plan["plan_id"] == "2026-09-24-s1-default-top2-buffer2"
    assert [(row["symbol"], row["side"], row["qty"]) for row in plan["orders"]] == [
        ("000002.SZ", "buy", 500),
        ("000099.SZ", "sell", 200),
    ]
    assert plan["skipped"][0]["reason"] == "already_held"


def test_manual_qmt_order_plan_is_saved_and_loaded(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "ScreenerService", FakeScreenerService)
    monkeypatch.setattr(live.strategy_config, "load_override", lambda data_dir, strategy_id: {})
    monkeypatch.setattr(live.paper, "overview", lambda data_dir, account_id="default": _overview())
    monkeypatch.setattr(live.paper, "load_positions", lambda data_dir, account_id="default": _positions())

    plan = live.create_manual_qmt_order_plan(
        tmp_path,
        _repo(tmp_path),
        FakeEngine(),
        {
            "strategy_id": "s1",
            "buy_symbols": ["000002.SZ"],
            "sell_symbols": ["000099.SZ", "000001.SZ"],
            "account": "default",
            "as_of": date(2026, 9, 24),
            "top_n": 2,
            "buffer_n": 2,
            "amount_per_symbol": 10000,
        },
    )
    loaded = live.load_qmt_order_plan(tmp_path)

    assert loaded["plan_id"] == plan["plan_id"]
    assert [(row["symbol"], row["side"], row["qty"]) for row in loaded["orders"]] == [
        ("000002.SZ", "buy", 500),
        ("000099.SZ", "sell", 200),
    ]
    assert loaded["skipped"] == [
        {"symbol": "000001.SZ", "side": "sell", "reason": "not_reached_hold_cycle", "message": "未达到策略持有周期"}
    ]


def test_manual_qmt_order_plan_skips_sell_before_strategy_cycle(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "ScreenerService", FakeScreenerService)
    monkeypatch.setattr(live.strategy_config, "load_override", lambda data_dir, strategy_id: {})
    monkeypatch.setattr(live.paper, "overview", lambda data_dir, account_id="default": _overview())
    monkeypatch.setattr(live.paper, "load_positions", lambda data_dir, account_id="default": {
        "000099.SZ": {"symbol": "000099.SZ", "lots": [{"date": "2026-09-23", "qty": 200}]},
    })

    plan = live.create_manual_qmt_order_plan(
        tmp_path,
        _repo(tmp_path),
        FakeEngine(),
        {
            "strategy_id": "s1",
            "buy_symbols": [],
            "sell_symbols": ["000099.SZ"],
            "account": "default",
            "as_of": date(2026, 9, 24),
            "top_n": 2,
            "buffer_n": 2,
            "amount_per_symbol": 10000,
        },
    )

    assert plan["orders"] == []
    assert plan["skipped"] == [
        {"symbol": "000099.SZ", "side": "sell", "reason": "not_reached_hold_cycle", "message": "未达到策略持有周期"}
    ]


def test_qmt_order_plan_latest_is_scoped_by_strategy_and_account(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "ScreenerService", FakeScreenerService)
    monkeypatch.setattr(live.strategy_config, "load_override", lambda data_dir, strategy_id: {})
    monkeypatch.setattr(live.paper, "overview", lambda data_dir, account_id="default": _overview())
    monkeypatch.setattr(live.paper, "load_positions", lambda data_dir, account_id="default": _positions())

    plan = live.create_manual_qmt_order_plan(
        tmp_path,
        _repo(tmp_path),
        FakeEngine(),
        {
            "strategy_id": "s1",
            "buy_symbols": ["000002.SZ"],
            "sell_symbols": [],
            "account": "default",
            "as_of": date(2026, 9, 24),
            "top_n": 2,
            "buffer_n": 2,
            "amount_per_symbol": 10000,
        },
    )

    assert live.load_qmt_order_plan(tmp_path, strategy_id="s1", account="default")["plan_id"] == plan["plan_id"]
    mismatched_account = live.load_qmt_order_plan(tmp_path, strategy_id="s1", account="other")
    mismatched_strategy = live.load_qmt_order_plan(tmp_path, strategy_id="other", account="default")

    assert mismatched_account["plan_id"] == "none"
    assert mismatched_account["orders"] == []
    assert mismatched_account["account"] == "other"
    assert mismatched_strategy["plan_id"] == "none"
    assert mismatched_strategy["strategy_id"] == "other"


def test_qmt_order_plan_latest_ignores_old_buffer_sell_plan(tmp_path):
    path = live._qmt_plan_scoped_path(tmp_path, "s1", "default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "plan_id": "old",
        "mode": "preview",
        "generated_at": "2026-09-24T10:00:00",
        "trade_date": "2026-09-24",
        "strategy_id": "s1",
        "strategy_name": "策略一",
        "account": "default",
        "asset_type": "stock",
        "timeframe": "1d",
        "top_n": 2,
        "buffer_n": 2,
        "amount_per_symbol": 10000,
        "orders": [{"symbol": "000099.SZ", "side": "sell", "qty": 200, "reason": "人工计划: 跌出缓冲池"}],
        "skipped": [],
        "notice": "",
    }, ensure_ascii=False), encoding="utf-8")

    loaded = live.load_qmt_order_plan(tmp_path, strategy_id="s1", account="default")

    assert loaded["plan_id"] == "none"
    assert loaded["orders"] == []


def test_qmt_order_plan_latest_rejects_strategy_not_bound_to_account(monkeypatch, tmp_path):
    monkeypatch.setattr(live.paper_auto, "load_auto_rules", lambda data_dir, account="default": [
        {
            "id": "r1",
            "enabled": True,
            "match_kind": "strategy",
            "match_id": "s1",
            "side": "follow",
        }
    ])
    path = live._qmt_plan_scoped_path(tmp_path, "legacy", "default")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "plan_id": "legacy-plan",
        "mode": "preview",
        "generated_at": "2026-09-24T10:00:00",
        "trade_date": "2026-09-24",
        "strategy_id": "legacy",
        "strategy_name": "旧策略",
        "account": "default",
        "asset_type": "stock",
        "timeframe": "1d",
        "top_n": 2,
        "buffer_n": 2,
        "max_hold_days": 5,
        "amount_per_symbol": 10000,
        "orders": [{"symbol": "000099.SZ", "side": "sell", "qty": 200, "reason": "人工计划: 持有周期到期(5个交易日)"}],
        "skipped": [],
        "notice": "",
    }, ensure_ascii=False), encoding="utf-8")

    loaded = live.load_qmt_order_plan(tmp_path, strategy_id="legacy", account="default")

    assert loaded["plan_id"] == "none"
    assert loaded["orders"] == []
    assert loaded["notice"] == "当前账号未绑定该策略；请使用账号已启用的策略跟随规则生成 QMT 预览计划。"


def test_buy_selected_skips_held_and_outside_pool(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "ScreenerService", FakeScreenerService)
    monkeypatch.setattr(live.strategy_config, "load_override", lambda data_dir, strategy_id: {})
    monkeypatch.setattr(live.paper, "overview", lambda data_dir, account_id="default": _overview())
    monkeypatch.setattr(live.paper, "load_positions", lambda data_dir, account_id="default": _positions())
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


def test_sell_out_of_buffer_uses_strategy_hold_cycle(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "ScreenerService", FakeScreenerService)
    monkeypatch.setattr(live.strategy_config, "load_override", lambda data_dir, strategy_id: {})
    monkeypatch.setattr(live.paper, "overview", lambda data_dir, account_id="default": _overview())
    monkeypatch.setattr(live.paper, "load_positions", lambda data_dir, account_id="default": _positions())

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
        {"symbol": "000001.SZ", "reason": "not_reached_hold_cycle", "message": "未达到策略持有周期"}
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
