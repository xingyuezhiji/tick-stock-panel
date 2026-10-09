"""Live console domain logic built on top of strategy screening and paper trading."""
from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.services.screener import ScreenerService
from app.strategy import config as strategy_config
from app.strategy import paper
from app.strategy.live_brokers import get_broker


DEFAULT_TOP_N = 30
DEFAULT_BUFFER_N = 45


def _safe_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, date):
        return value.isoformat()
    return value


def _safe_row(row: dict) -> dict:
    return {str(k): _safe_value(v) for k, v in row.items()}


def _result_rows(result: Any) -> list[dict]:
    if is_dataclass(result):
        data = asdict(result)
    elif isinstance(result, dict):
        data = result
    else:
        data = {"rows": getattr(result, "rows", [])}
    return [_safe_row(dict(row)) for row in data.get("rows", [])]


def _strategy_limit(engine, strategy_id: str, overrides: dict) -> int:
    strategy = engine.get(strategy_id)
    if "display_limit" in overrides:
        value = overrides.get("display_limit")
        if value not in (None, 0):
            return max(1, int(value))
    value = strategy.meta.get("limit", DEFAULT_TOP_N)
    if value in (None, 0):
        return DEFAULT_TOP_N
    return max(1, int(value))


def _price_from_row(row: dict) -> float | None:
    for key in ("raw_close", "close", "price", "last_price", "open"):
        value = row.get(key)
        try:
            if value is not None and math.isfinite(float(value)) and float(value) > 0:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _holding_map(overview: dict) -> dict[str, dict]:
    return {
        str(row.get("symbol")): dict(row)
        for row in overview.get("holdings", []) or []
        if row.get("symbol")
    }


def _normalise_candidate(row: dict, rank: int, holding: dict | None) -> dict:
    held_qty = float(holding.get("qty", 0)) if holding else 0.0
    out = {
        **row,
        "rank": rank,
        "symbol": str(row.get("symbol") or ""),
        "name": row.get("name") or row.get("display_name") or "",
        "score": _safe_value(row.get("score")),
        "ref_price": _price_from_row(row),
        "held_qty": held_qty,
        "in_position": held_qty > 0,
        "suggested_action": "hold" if held_qty > 0 else "buy",
    }
    return _safe_row(out)


def _normalise_holding(row: dict, buffer_symbols: set[str], rank_by_symbol: dict[str, int], row_by_symbol: dict[str, dict]) -> dict:
    symbol = str(row.get("symbol") or "")
    in_buffer = symbol in buffer_symbols
    strategy_row = row_by_symbol.get(symbol, {})
    out = {
        **row,
        "symbol": symbol,
        "name": row.get("name") or strategy_row.get("name") or strategy_row.get("display_name") or "",
        "rank": rank_by_symbol.get(symbol),
        "in_buffer": in_buffer,
        "suggested_action": "hold" if in_buffer else "sell",
    }
    return _safe_row(out)


def build_strategy_pool(
    repo,
    engine,
    *,
    strategy_id: str,
    account_id: str = paper.DEFAULT_ACCOUNT_ID,
    as_of: date | None = None,
    asset_type: str = "stock",
    timeframe: str = "1d",
    top_n: int | None = None,
    buffer_n: int | None = None,
) -> dict:
    """Run one strategy and compare candidates with current paper holdings."""
    if engine is None or not engine.has(strategy_id):
        raise ValueError(f"unknown strategy: {strategy_id}")
    strategy = engine.get(strategy_id)
    if strategy.meta.get("research_only"):
        raise ValueError(f"unknown strategy: {strategy_id}")

    data_dir = repo.store.data_dir
    account_id = paper.validate_account_id(account_id)
    svc = ScreenerService(repo, asset_type=asset_type)
    run_date = as_of or svc.latest_date()
    if run_date is None:
        raise ValueError("无可用数据日期")

    overrides = strategy_config.load_override(data_dir, strategy_id) or {}
    default_limit = _strategy_limit(engine, strategy_id, overrides)
    top = max(1, int(top_n or default_limit or DEFAULT_TOP_N))
    buffer = max(top, int(buffer_n or max(default_limit, DEFAULT_BUFFER_N)))
    run_overrides = dict(overrides)
    run_overrides["display_limit"] = buffer
    params = dict(run_overrides.get("params") or {})

    context = svc.build_strategy_context(
        engine,
        run_date,
        [strategy_id],
        timeframe=timeframe,
        params_map={strategy_id: params},
        overrides_map={strategy_id: run_overrides},
    )
    result = engine.run(
        strategy_id,
        context,
        params=params,
        overrides=run_overrides,
    )
    rows = _result_rows(result)
    ranked_rows = [row for row in rows if row.get("symbol")]
    rank_by_symbol = {
        str(row["symbol"]): idx
        for idx, row in enumerate(ranked_rows, start=1)
    }
    row_by_symbol = {str(row["symbol"]): row for row in ranked_rows}
    buy_rows = ranked_rows[:top]
    buffer_rows = ranked_rows[:buffer]
    buy_symbols = {str(row["symbol"]) for row in buy_rows}
    buffer_symbols = {str(row["symbol"]) for row in buffer_rows}

    overview = paper.overview(data_dir, account_id=account_id)
    holdings = _holding_map(overview)
    candidates = [
        _normalise_candidate(row, idx, holdings.get(str(row["symbol"])))
        for idx, row in enumerate(buy_rows, start=1)
    ]
    holding_rows = [
        _normalise_holding(row, buffer_symbols, rank_by_symbol, row_by_symbol)
        for row in overview.get("holdings", []) or []
    ]

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy.meta.get("name", strategy_id),
        "as_of": run_date.isoformat(),
        "account_id": account_id,
        "asset_type": asset_type,
        "timeframe": timeframe,
        "top_n": top,
        "buffer_n": buffer,
        "total": len(ranked_rows),
        "buy_symbols": sorted(buy_symbols),
        "buffer_symbols": sorted(buffer_symbols),
        "candidates": candidates,
        "holdings": holding_rows,
        "overview": overview,
    }


def _broker_disabled_result(broker_id: str, symbols: list[str], message: str) -> dict:
    return {
        "broker": broker_id,
        "created": [],
        "skipped": [
            {"symbol": symbol, "reason": "broker_disabled", "message": message}
            for symbol in symbols
        ],
        "errors": [{"reason": "broker_disabled", "message": message}],
    }


def buy_selected(data_dir: Path, repo, engine, body: dict) -> dict:
    symbols = [str(s) for s in body.get("symbols", []) if str(s or "").strip()]
    broker_id = str(body.get("broker") or "paper")
    broker = get_broker(broker_id)
    if not broker.enabled:
        return _broker_disabled_result(broker.id, symbols, getattr(broker, "message", "broker disabled"))

    pool = build_strategy_pool(
        repo,
        engine,
        strategy_id=str(body["strategy_id"]),
        account_id=str(body.get("account") or paper.DEFAULT_ACCOUNT_ID),
        as_of=body.get("as_of"),
        asset_type=str(body.get("asset_type") or "stock"),
        timeframe=str(body.get("timeframe") or "1d"),
        top_n=body.get("top_n"),
        buffer_n=body.get("buffer_n"),
    )
    candidate_by_symbol = {row["symbol"]: row for row in pool["candidates"]}
    holding_by_symbol = _holding_map(pool.get("overview", {}))
    created: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for symbol in symbols:
        row = candidate_by_symbol.get(symbol)
        if row is None:
            skipped.append({"symbol": symbol, "reason": "not_in_buy_pool", "message": "不在当前买入候选池"})
            continue
        if float(holding_by_symbol.get(symbol, {}).get("qty", 0) or 0) > 0:
            skipped.append({"symbol": symbol, "reason": "already_held", "message": "已在持仓中"})
            continue
        order, err = broker.create_order(
            data_dir,
            account_id=pool["account_id"],
            symbol=symbol,
            side="buy",
            amount=float(body.get("amount_per_symbol") or 0) or None,
            order_type=str(body.get("order_type") or "next_open"),
            asset_type=str(body.get("asset_type") or "stock"),
            ref_price=row.get("ref_price"),
        )
        if err:
            errors.append({"symbol": symbol, "reason": "order_rejected", "message": err})
        elif order:
            created.append(order)
    return {"broker": broker.id, "created": created, "skipped": skipped, "errors": errors}


def sell_out_of_buffer(data_dir: Path, repo, engine, body: dict) -> dict:
    symbols = [str(s) for s in body.get("symbols", []) if str(s or "").strip()]
    broker_id = str(body.get("broker") or "paper")
    broker = get_broker(broker_id)
    if not broker.enabled:
        return _broker_disabled_result(broker.id, symbols, getattr(broker, "message", "broker disabled"))

    pool = build_strategy_pool(
        repo,
        engine,
        strategy_id=str(body["strategy_id"]),
        account_id=str(body.get("account") or paper.DEFAULT_ACCOUNT_ID),
        as_of=body.get("as_of"),
        asset_type=str(body.get("asset_type") or "stock"),
        timeframe=str(body.get("timeframe") or "1d"),
        top_n=body.get("top_n"),
        buffer_n=body.get("buffer_n"),
    )
    holding_by_symbol = {row["symbol"]: row for row in pool["holdings"]}
    created: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for symbol in symbols:
        row = holding_by_symbol.get(symbol)
        if row is None:
            skipped.append({"symbol": symbol, "reason": "invalid_symbol", "message": "当前账户无该持仓"})
            continue
        if row.get("in_buffer"):
            skipped.append({"symbol": symbol, "reason": "still_in_buffer", "message": "仍在缓冲候选池"})
            continue
        available_qty = int(float(row.get("available_qty") or 0))
        if available_qty <= 0:
            skipped.append({"symbol": symbol, "reason": "no_available_qty", "message": "无可卖数量"})
            continue
        order, err = broker.create_order(
            data_dir,
            account_id=pool["account_id"],
            symbol=symbol,
            side="sell",
            qty=available_qty,
            order_type=str(body.get("order_type") or "next_open"),
            asset_type=str(row.get("asset_type") or body.get("asset_type") or "stock"),
            ref_price=row.get("last_price"),
        )
        if err:
            errors.append({"symbol": symbol, "reason": "order_rejected", "message": err})
        elif order:
            created.append(order)
    return {"broker": broker.id, "created": created, "skipped": skipped, "errors": errors}
