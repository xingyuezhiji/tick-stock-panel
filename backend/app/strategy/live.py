"""Live console domain logic built on top of strategy screening and paper trading."""
from __future__ import annotations

import math
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services.fs_utils import atomic_write_text
from app.services.screener import ScreenerService
from app.strategy import config as strategy_config
from app.strategy import paper
from app.strategy import paper_auto
from app.strategy.live_brokers import get_broker


DEFAULT_TOP_N = 30
DEFAULT_BUFFER_N = 45
DEFAULT_QMT_AMOUNT_PER_SYMBOL = 10000.0
_DATE_DIR_RE = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")


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


def _lot_qty_from_amount(amount: float, price: float | None) -> int:
    if price is None or price <= 0 or amount <= 0:
        return 0
    return int(amount // (price * paper.LOT_SIZE)) * paper.LOT_SIZE


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _local_trading_days(data_dir: Path) -> list[date]:
    root = Path(data_dir) / "kline_daily"
    out: list[date] = []
    try:
        for item in root.iterdir():
            match = _DATE_DIR_RE.match(item.name)
            if not item.is_dir() or match is None:
                continue
            try:
                out.append(date.fromisoformat(match.group(1)))
            except ValueError:
                continue
    except OSError:
        return []
    return sorted(set(out))


def _trading_day_distance(data_dir: Path, start: date, end: date) -> int:
    if end <= start:
        return 0
    days = _local_trading_days(data_dir)
    if not days:
        return (end - start).days
    try:
        return max(0, days.index(end) - days.index(start))
    except ValueError:
        return sum(1 for day in days if start < day <= end)


def _strategy_cycle_days(data_dir: Path, engine, strategy_id: str) -> int:
    strategy = engine.get(strategy_id)
    overrides = strategy_config.load_override(data_dir, strategy_id) or {}
    value = overrides.get("max_hold_days", getattr(strategy, "max_hold_days", None))
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = 5
    return max(1, days)


def _matured_available_qty(data_dir: Path, position: dict | None, run_date: date, cycle_days: int) -> tuple[int, int]:
    if not position:
        return 0, 0
    today = paper.cn_today()
    matured_qty = 0
    max_hold_days = 0
    for lot in position.get("lots", []) or []:
        lot_date = _parse_date(lot.get("date"))
        if lot_date is None:
            continue
        hold_days = _trading_day_distance(data_dir, lot_date, run_date)
        max_hold_days = max(max_hold_days, hold_days)
        if lot_date >= today or hold_days < cycle_days:
            continue
        try:
            matured_qty += int(float(lot.get("qty") or 0))
        except (TypeError, ValueError):
            continue
    return max(0, matured_qty), max_hold_days


def _qmt_plan_path(data_dir: Path) -> Path:
    return Path(data_dir) / "live" / "qmt_order_plan_latest.json"


def _qmt_plan_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())


def _qmt_plan_scoped_path(data_dir: Path, strategy_id: str, account: str) -> Path:
    return Path(data_dir) / "live" / "qmt_order_plans" / f"{_qmt_plan_key(strategy_id)}__{_qmt_plan_key(account)}.json"


def empty_qmt_order_plan(strategy_id: str = "", account: str = paper.DEFAULT_ACCOUNT_ID) -> dict:
    return {
        "plan_id": "none",
        "mode": "preview",
        "generated_at": None,
        "trade_date": "",
        "strategy_id": strategy_id,
        "strategy_name": "",
        "account": account,
        "asset_type": "stock",
        "timeframe": "1d",
        "top_n": 0,
        "buffer_n": 0,
        "amount_per_symbol": DEFAULT_QMT_AMOUNT_PER_SYMBOL,
        "orders": [],
        "skipped": [],
        "notice": "暂无人工计划单；请先在 TSP /live 页面点击生成 QMT 预览计划。",
    }


def _read_qmt_order_plan(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _qmt_order_plan_matches(data: dict, *, strategy_id: str = "", account: str = "") -> bool:
    if strategy_id and str(data.get("strategy_id") or "") != strategy_id:
        return False
    if account and str(data.get("account") or "") != account:
        return False
    return True


def _qmt_order_plan_uses_current_cycle_logic(data: dict) -> bool:
    if data.get("plan_id") == "none":
        return True
    if data.get("max_hold_days") is None:
        return False
    for order in data.get("orders") or []:
        if order.get("side") == "sell" and "跌出缓冲池" in str(order.get("reason") or ""):
            return False
    return True


def _account_bound_strategy_ids(data_dir: Path, account: str) -> list[str]:
    ids: list[str] = []
    for rule in paper_auto.load_auto_rules(data_dir, account):
        if not rule.get("enabled"):
            continue
        if rule.get("match_kind") != "strategy" or rule.get("side") != "follow":
            continue
        match_id = str(rule.get("match_id") or "")
        if match_id and match_id not in ids:
            ids.append(match_id)
    return ids


def _strategy_allowed_for_account(data_dir: Path, strategy_id: str, account: str) -> bool:
    bound = _account_bound_strategy_ids(data_dir, account)
    return not bound or not strategy_id or strategy_id in bound


def load_qmt_order_plan(data_dir: Path, *, strategy_id: str = "", account: str = paper.DEFAULT_ACCOUNT_ID) -> dict:
    requested_strategy = str(strategy_id or "")
    requested_account = str(account or paper.DEFAULT_ACCOUNT_ID)
    if not _strategy_allowed_for_account(data_dir, requested_strategy, requested_account):
        plan = empty_qmt_order_plan(strategy_id=requested_strategy, account=requested_account)
        plan["notice"] = "当前账号未绑定该策略；请使用账号已启用的策略跟随规则生成 QMT 预览计划。"
        return plan
    paths: list[Path] = []
    if requested_strategy and requested_account:
        paths.append(_qmt_plan_scoped_path(data_dir, requested_strategy, requested_account))
    paths.append(_qmt_plan_path(data_dir))
    for path in paths:
        if not path.exists():
            continue
        data = _read_qmt_order_plan(path)
        if data is None:
            continue
        if not _qmt_order_plan_uses_current_cycle_logic(data):
            continue
        if _qmt_order_plan_matches(data, strategy_id=requested_strategy, account=requested_account):
            return data
    plan = empty_qmt_order_plan(strategy_id=requested_strategy, account=requested_account)
    plan["notice"] = "暂无匹配当前策略和账号的人工计划单；请先在 TSP /live 页面为该策略和账号生成 QMT 预览计划。"
    return plan


def _save_qmt_order_plan(data_dir: Path, plan: dict) -> None:
    global_path = _qmt_plan_path(data_dir)
    scoped_path = _qmt_plan_scoped_path(data_dir, str(plan.get("strategy_id") or ""), str(plan.get("account") or ""))
    global_path.parent.mkdir(parents=True, exist_ok=True)
    scoped_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(plan, ensure_ascii=False, indent=2)
    atomic_write_text(scoped_path, payload)
    atomic_write_text(global_path, payload)


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


def _normalise_holding(
    row: dict,
    buffer_symbols: set[str],
    rank_by_symbol: dict[str, int],
    row_by_symbol: dict[str, dict],
    *,
    cycle_days: int,
    cycle_sell_qty: int = 0,
    hold_days: int = 0,
) -> dict:
    symbol = str(row.get("symbol") or "")
    in_buffer = symbol in buffer_symbols
    strategy_row = row_by_symbol.get(symbol, {})
    available_qty = int(float(row.get("available_qty") or 0))
    sell_qty = min(max(0, cycle_sell_qty), max(0, available_qty))
    out = {
        **row,
        "symbol": symbol,
        "name": row.get("name") or strategy_row.get("name") or strategy_row.get("display_name") or "",
        "rank": rank_by_symbol.get(symbol),
        "in_buffer": in_buffer,
        "max_hold_days": cycle_days,
        "hold_days": hold_days,
        "cycle_sell_qty": sell_qty,
        "cycle_sellable": sell_qty > 0,
        "suggested_action": "sell" if sell_qty > 0 else "hold",
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
    cycle_days = _strategy_cycle_days(data_dir, engine, strategy_id)
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
    positions = paper.load_positions(data_dir, account_id)
    holdings = _holding_map(overview)
    candidates = [
        _normalise_candidate(row, idx, holdings.get(str(row["symbol"])))
        for idx, row in enumerate(buy_rows, start=1)
    ]
    run_date_value = _parse_date(run_date) or run_date
    holding_rows = []
    for row in overview.get("holdings", []) or []:
        symbol = str(row.get("symbol") or "")
        cycle_sell_qty, hold_days = _matured_available_qty(data_dir, positions.get(symbol), run_date_value, cycle_days)
        holding_rows.append(_normalise_holding(
            row,
            buffer_symbols,
            rank_by_symbol,
            row_by_symbol,
            cycle_days=cycle_days,
            cycle_sell_qty=cycle_sell_qty,
            hold_days=hold_days,
        ))

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy.meta.get("name", strategy_id),
        "as_of": run_date.isoformat(),
        "account_id": account_id,
        "asset_type": asset_type,
        "timeframe": timeframe,
        "top_n": top,
        "buffer_n": buffer,
        "max_hold_days": cycle_days,
        "total": len(ranked_rows),
        "buy_symbols": sorted(buy_symbols),
        "buffer_symbols": sorted(buffer_symbols),
        "candidates": candidates,
        "holdings": holding_rows,
        "overview": overview,
    }


def build_qmt_order_plan(
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
    amount_per_symbol: float = DEFAULT_QMT_AMOUNT_PER_SYMBOL,
    include_sells: bool = True,
) -> dict:
    """Build a read-only order plan for QMT scripts to preview.

    This does not create paper orders or real broker orders. It only converts the
    current live pool into buy/sell instructions that an external QMT strategy can
    read and print.
    """
    pool = build_strategy_pool(
        repo,
        engine,
        strategy_id=strategy_id,
        account_id=account_id,
        as_of=as_of,
        asset_type=asset_type,
        timeframe=timeframe,
        top_n=top_n,
        buffer_n=buffer_n,
    )
    orders: list[dict] = []
    skipped: list[dict] = []
    amount = float(amount_per_symbol or 0)

    for row in pool.get("candidates", []):
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        if row.get("in_position"):
            skipped.append({"symbol": symbol, "side": "buy", "reason": "already_held", "message": "已在持仓中"})
            continue
        qty = _lot_qty_from_amount(amount, row.get("ref_price"))
        if qty <= 0:
            skipped.append({"symbol": symbol, "side": "buy", "reason": "invalid_qty", "message": "参考价缺失或金额不足一手"})
            continue
        orders.append({
            "symbol": symbol,
            "name": row.get("name") or "",
            "side": "buy",
            "qty": qty,
            "amount": amount,
            "ref_price": row.get("ref_price"),
            "price_type": "latest",
            "rank": row.get("rank"),
            "reason": f"策略候选Top{pool['top_n']}",
        })

    if include_sells:
        for row in pool.get("holdings", []):
            symbol = str(row.get("symbol") or "")
            if not symbol:
                continue
            qty = int(float(row.get("cycle_sell_qty") or 0))
            if qty <= 0:
                skipped.append({"symbol": symbol, "side": "sell", "reason": "not_reached_hold_cycle", "message": "未达到策略持有周期"})
                continue
            orders.append({
                "symbol": symbol,
                "name": row.get("name") or "",
                "side": "sell",
                "qty": qty,
                "amount": None,
                "ref_price": row.get("last_price"),
                "price_type": "latest",
                "rank": row.get("rank"),
                "reason": f"持有周期到期({pool['max_hold_days']}个交易日)",
            })

    return {
        "plan_id": f"{pool['as_of']}-{strategy_id}-{pool['account_id']}-top{pool['top_n']}-buffer{pool['buffer_n']}",
        "mode": "preview",
        "trade_date": pool["as_of"],
        "strategy_id": strategy_id,
        "strategy_name": pool["strategy_name"],
        "account": pool["account_id"],
        "asset_type": pool["asset_type"],
        "timeframe": pool["timeframe"],
        "top_n": pool["top_n"],
        "buffer_n": pool["buffer_n"],
        "max_hold_days": pool["max_hold_days"],
        "amount_per_symbol": amount,
        "orders": orders,
        "skipped": skipped,
        "notice": "预览清单不会自动下单；QMT 策略需人工确认后再接执行逻辑。",
    }


def create_manual_qmt_order_plan(data_dir: Path, repo, engine, body: dict) -> dict:
    buy_symbols = [str(s) for s in body.get("buy_symbols", []) if str(s or "").strip()]
    sell_symbols = [str(s) for s in body.get("sell_symbols", []) if str(s or "").strip()]
    strategy_id = str(body["strategy_id"])
    account_id = paper.validate_account_id(str(body.get("account") or paper.DEFAULT_ACCOUNT_ID))
    if not _strategy_allowed_for_account(data_dir, strategy_id, account_id):
        plan = empty_qmt_order_plan(strategy_id=strategy_id, account=account_id)
        plan["notice"] = "当前账号未绑定该策略；请切换到账号实际使用的策略后再生成 QMT 预览计划。"
        return plan
    amount = float(body.get("amount_per_symbol") or DEFAULT_QMT_AMOUNT_PER_SYMBOL)
    pool = build_strategy_pool(
        repo,
        engine,
        strategy_id=strategy_id,
        account_id=account_id,
        as_of=body.get("as_of"),
        asset_type=str(body.get("asset_type") or "stock"),
        timeframe=str(body.get("timeframe") or "1d"),
        top_n=body.get("top_n"),
        buffer_n=body.get("buffer_n"),
    )
    candidate_by_symbol = {row["symbol"]: row for row in pool["candidates"]}
    holding_by_symbol = {row["symbol"]: row for row in pool["holdings"]}
    orders: list[dict] = []
    skipped: list[dict] = []

    for symbol in buy_symbols:
        row = candidate_by_symbol.get(symbol)
        if row is None:
            skipped.append({"symbol": symbol, "side": "buy", "reason": "not_in_buy_pool", "message": "不在当前买入候选池"})
            continue
        if row.get("in_position"):
            skipped.append({"symbol": symbol, "side": "buy", "reason": "already_held", "message": "已在持仓中"})
            continue
        qty = _lot_qty_from_amount(amount, row.get("ref_price"))
        if qty <= 0:
            skipped.append({"symbol": symbol, "side": "buy", "reason": "invalid_qty", "message": "参考价缺失或金额不足一手"})
            continue
        orders.append({
            "symbol": symbol,
            "name": row.get("name") or "",
            "side": "buy",
            "qty": qty,
            "amount": amount,
            "ref_price": row.get("ref_price"),
            "price_type": "latest",
            "rank": row.get("rank"),
            "reason": f"人工计划: 策略候选Top{pool['top_n']}",
        })

    for symbol in sell_symbols:
        row = holding_by_symbol.get(symbol)
        if row is None:
            skipped.append({"symbol": symbol, "side": "sell", "reason": "invalid_symbol", "message": "不在当前持仓中"})
            continue
        qty = int(float(row.get("cycle_sell_qty") or 0))
        if qty <= 0:
            skipped.append({"symbol": symbol, "side": "sell", "reason": "not_reached_hold_cycle", "message": "未达到策略持有周期"})
            continue
        orders.append({
            "symbol": symbol,
            "name": row.get("name") or "",
            "side": "sell",
            "qty": qty,
            "amount": None,
            "ref_price": row.get("last_price"),
            "price_type": "latest",
            "rank": row.get("rank"),
            "reason": f"人工计划: 持有周期到期({pool['max_hold_days']}个交易日)",
        })

    generated_at = datetime.now().isoformat(timespec="seconds")
    plan = {
        "plan_id": f"{pool['as_of']}-{strategy_id}-{pool['account_id']}-{generated_at.replace(':', '').replace('-', '').replace('T', '-')}",
        "mode": "preview",
        "generated_at": generated_at,
        "trade_date": pool["as_of"],
        "strategy_id": strategy_id,
        "strategy_name": pool["strategy_name"],
        "account": pool["account_id"],
        "asset_type": pool["asset_type"],
        "timeframe": pool["timeframe"],
        "top_n": pool["top_n"],
        "buffer_n": pool["buffer_n"],
        "max_hold_days": pool["max_hold_days"],
        "amount_per_symbol": amount,
        "orders": orders,
        "skipped": skipped,
        "notice": "人工计划单已生成；QMT 预览脚本只会读取并打印，不会自动下单。",
    }
    _save_qmt_order_plan(data_dir, plan)
    return plan


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
        sell_qty = int(float(row.get("cycle_sell_qty") or 0))
        if sell_qty <= 0:
            skipped.append({"symbol": symbol, "reason": "not_reached_hold_cycle", "message": "未达到策略持有周期"})
            continue
        order, err = broker.create_order(
            data_dir,
            account_id=pool["account_id"],
            symbol=symbol,
            side="sell",
            qty=sell_qty,
            order_type=str(body.get("order_type") or "next_open"),
            asset_type=str(row.get("asset_type") or body.get("asset_type") or "stock"),
            ref_price=row.get("last_price"),
        )
        if err:
            errors.append({"symbol": symbol, "reason": "order_rejected", "message": err})
        elif order:
            created.append(order)
    return {"broker": broker.id, "created": created, "skipped": skipped, "errors": errors}
