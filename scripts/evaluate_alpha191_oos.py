"""Evaluate Alpha191 factors from the public dashboard repo with TSP settings."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import shutil
import sys
import tempfile
import time
import traceback
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.backtest.engine import BacktestEngine
from app.backtest.strategy import StrategyBacktestConfig, StrategyBacktestService
from app.strategy import config as strategy_config
from app.strategy.engine import StrategyEngine
from app.tickflow.repository import DataStore, KlineRepository


DEFAULT_PARAMS = {
    "n_buy": 10,
    "n_hold": 15,
    "min_listed_days": 60,
    "amount_window": 20,
    "min_avg_amount": 30_000_000.0,
}
BASELINE_STRATEGY_ID = "ai_alphagpt_round935_c12_jump_delay"


HELPER_CODE = r'''
"""Trusted temporary bridge from Alpha191 pandas factors to TSP matrix signals."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

from app.backtest.matrix import MarketDataMatrix, SignalMatrix, make_signal_matrix, valid_rolling_mean

_ALPHA_CODE_DIR = Path(__file__).resolve().parent / "_alpha191_code"
if str(_ALPHA_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_ALPHA_CODE_DIR))
import engine


DEFAULT_PARAMS = [
    {"id": "n_buy", "label": "Top N buys", "type": "int", "default": 10, "min": 1, "max": 200, "step": 1},
    {"id": "n_hold", "label": "Hold buffer N", "type": "int", "default": 15, "min": 1, "max": 300, "step": 1},
    {"id": "min_listed_days", "label": "Minimum listed days", "type": "int", "default": 60, "min": 1, "max": 250, "step": 1},
    {"id": "amount_window", "label": "Amount MA window", "type": "int", "default": 20, "min": 1, "max": 120, "step": 1},
    {"id": "min_avg_amount", "label": "Minimum average amount", "type": "float", "default": 30000000.0, "min": 0.0, "max": 1000000000.0, "step": 1000000.0},
]
_CTX_CACHE: dict[tuple, SimpleNamespace] = {}
_FACTOR_CACHE: dict[tuple[tuple, int], np.ndarray] = {}


def build_meta(strategy_id: str, alpha_id: int, direction: str, formula: str) -> dict:
    return {
        "id": strategy_id,
        "name": f"Alpha191 alpha{alpha_id:03d} {direction}",
        "description": formula,
        "tags": ["Alpha191", "temporary", "live_like_screen", direction],
        "asset_types": ["stock"],
        "timeframes": ["1d"],
        "basic_filter": {"enabled": False},
        "params": DEFAULT_PARAMS,
        "scoring": {},
        "order_by": "score",
        "descending": True,
        "limit": 15,
        "rebalance": {"mode": "equal_weight"},
        "stop_loss": None,
        "max_hold_days": None,
        "research_only": False,
    }


def _int_param(params: dict, name: str, default: int, minimum: int) -> int:
    try:
        value = int(params.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _float_param(params: dict, name: str, default: float, minimum: float) -> float:
    try:
        value = float(params.get(name, default))
    except (TypeError, ValueError):
        value = default
    if not np.isfinite(value):
        return default
    return max(minimum, value)


def _field_or_nan(market: MarketDataMatrix, name: str) -> np.ndarray:
    try:
        return market.field(name).astype(np.float64, copy=False)
    except Exception:
        return np.full(market.shape, np.nan, dtype=np.float64)


def _weekly_signal_mask(labels: tuple[str, ...]) -> np.ndarray:
    out = np.zeros(len(labels), dtype=bool)
    if len(labels) < 2:
        if labels:
            out[0] = date.fromisoformat(labels[0][:10]).weekday() >= 3
        return out
    days = [date.fromisoformat(label[:10]) for label in labels]
    weeks = [day.isocalendar()[:2] for day in days]
    for time_id in range(len(labels) - 1):
        if weeks[time_id + 1] != weeks[time_id]:
            out[time_id] = True
    out[-1] = out[-1] or days[-1].weekday() >= 3
    return out


def _score_rank(eligible: np.ndarray, value: np.ndarray) -> np.ndarray:
    score = np.zeros(value.shape, dtype=np.float32)
    for time_id in range(value.shape[0]):
        asset_ids = np.flatnonzero(eligible[time_id] & np.isfinite(value[time_id]))
        count = asset_ids.size
        if count == 0:
            continue
        order = asset_ids[np.argsort(-value[time_id, asset_ids], kind="stable")]
        if count == 1:
            score[time_id, order[0]] = np.float32(100.0)
            continue
        ranks = np.arange(count, dtype=np.float32)
        score[time_id, order] = (np.float32(1.0) - ranks / np.float32(count - 1)) * np.float32(100.0)
    return score


def _top_rank_mask(eligible: np.ndarray, value: np.ndarray, top_n: int) -> np.ndarray:
    result = np.zeros(eligible.shape, dtype=bool)
    for time_id in range(eligible.shape[0]):
        asset_ids = np.flatnonzero(eligible[time_id] & np.isfinite(value[time_id]))
        if asset_ids.size == 0:
            continue
        selected = asset_ids[np.argsort(-value[time_id, asset_ids], kind="stable")[:top_n]]
        result[time_id, selected] = True
    return result


def _eligible(market: MarketDataMatrix, params: dict) -> np.ndarray:
    amount_window = _int_param(params, "amount_window", 20, 1)
    min_listed = _int_param(params, "min_listed_days", 60, 1)
    min_avg_amount = _float_param(params, "min_avg_amount", 30_000_000.0, 0.0)
    amount = _field_or_nan(market, "amount")
    valid = (
        np.isfinite(market.open)
        & np.isfinite(market.close)
        & np.isfinite(market.volume)
        & (market.open > 0)
        & (market.close > 0)
        & (market.volume > 0)
    )
    amount_valid = np.isfinite(amount) & (amount > 0)
    avg_amount = valid_rolling_mean(amount.astype(np.float32), valid & amount_valid, amount_window)
    listed_days = np.cumsum(valid, axis=0)
    tradable = getattr(market, "tradable", np.ones(market.shape, dtype=bool))
    return valid & amount_valid & tradable & (listed_days >= min_listed) & (avg_amount >= min_avg_amount)


def _frame(values: np.ndarray, index: pd.DatetimeIndex, columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(values.astype(np.float64, copy=False), index=index, columns=columns)


def _market_cache_key(market: MarketDataMatrix) -> tuple:
    if market.timestamp_labels:
        first_label = market.timestamp_labels[0]
        last_label = market.timestamp_labels[-1]
    else:
        first_label = ""
        last_label = ""
    return (first_label, last_label, market.shape, tuple(market.symbols))


def _build_ctx(market: MarketDataMatrix) -> SimpleNamespace:
    cache_key = _market_cache_key(market)
    cached = _CTX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    index = pd.to_datetime([label[:10] for label in market.timestamp_labels])
    columns = tuple(market.symbols)
    open_ = _frame(market.open, index, columns)
    high = _frame(market.high, index, columns)
    low = _frame(market.low, index, columns)
    close = _frame(market.close, index, columns)
    volume = _frame(market.volume, index, columns)
    amount_array = _field_or_nan(market, "amount")
    if not np.isfinite(amount_array).any():
        amount_array = market.close.astype(np.float64) * market.volume.astype(np.float64)
    amount = _frame(amount_array, index, columns)
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap_values = amount_array / market.volume.astype(np.float64)
    vwap = _frame(vwap_values, index, columns)
    ret = close.pct_change(fill_method=None)

    bench_close = close.mean(axis=1, skipna=True)
    bench_open = open_.mean(axis=1, skipna=True)
    bc = pd.DataFrame(
        np.tile(bench_close.to_numpy(dtype=float)[:, None], (1, len(columns))),
        index=index,
        columns=columns,
    )
    bo = pd.DataFrame(
        np.tile(bench_open.to_numpy(dtype=float)[:, None], (1, len(columns))),
        index=index,
        columns=columns,
    )
    mkt = bc / bc.shift(1) - 1
    ctx = SimpleNamespace(O=open_, H=high, L=low, C=close, VWAP=vwap, V=volume, AMT=amount, RET=ret, BO=bo, BC=bc, MKT=mkt)
    _CTX_CACHE[cache_key] = ctx
    return ctx


def _coerce_factor(value, index: pd.DatetimeIndex, columns: tuple[str, ...]) -> np.ndarray:
    if isinstance(value, pd.DataFrame):
        frame = value
    elif isinstance(value, pd.Series):
        frame = pd.DataFrame(
            np.tile(value.reindex(index).to_numpy(dtype=float)[:, None], (1, len(columns))),
            index=index,
            columns=columns,
        )
    elif np.isscalar(value):
        frame = pd.DataFrame(float(value), index=index, columns=columns)
    else:
        frame = pd.DataFrame(value, index=index, columns=columns)
    frame = frame.replace([np.inf, -np.inf], np.nan).reindex(index=index, columns=columns)
    return frame.to_numpy(dtype=np.float32, copy=True)


def evaluate_alpha(market: MarketDataMatrix, alpha_id: int) -> np.ndarray:
    cache_key = (_market_cache_key(market), alpha_id)
    cached = _FACTOR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    ctx = _build_ctx(market)
    factor_func = engine.REGISTRY[alpha_id]
    value = factor_func(ctx)
    factor = _coerce_factor(value, ctx.C.index, tuple(ctx.C.columns))
    _FACTOR_CACHE[cache_key] = factor
    return factor


class Alpha191MatrixStrategy:
    def __init__(self, strategy_id: str, alpha_id: int, direction: str) -> None:
        self.strategy_id = strategy_id
        self.alpha_id = alpha_id
        self.direction = direction

    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume", "amount"})

    def required_warmup_bars(self, params: dict) -> int:
        amount_window = _int_param(params, "amount_window", 20, 1)
        min_listed = _int_param(params, "min_listed_days", 60, 1)
        return max(260, amount_window, min_listed) + 5

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        n_buy = _int_param(params, "n_buy", 10, 1)
        n_hold = max(n_buy, _int_param(params, "n_hold", 15, 1))
        raw_value = evaluate_alpha(market, self.alpha_id)
        value = -raw_value if self.direction == "low" else raw_value
        eligible = _eligible(market, params)
        score = _score_rank(eligible, value)
        signal_days = _weekly_signal_mask(market.timestamp_labels)
        buy_pool = _top_rank_mask(eligible, value, n_buy)
        buffer_pool = _top_rank_mask(eligible, value, n_hold)
        entry = buy_pool & signal_days[:, None]
        exit_ = (~buffer_pool) & signal_days[:, None]
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=(f"signal_{self.strategy_id}_top10",),
            exit_signal_ids=(f"signal_{self.strategy_id}_buffer15_exit",),
        )
'''


BOTTLENECK_FALLBACK_CODE = r'''
"""Small fallback for the Alpha191 operators used in this batch evaluation."""

from __future__ import annotations

import numpy as np


def _window_result(values, window, reducer):
    arr = np.asarray(values, dtype=float)
    out = np.full(arr.shape, np.nan, dtype=float)
    if arr.ndim != 2:
        raise ValueError("fallback bottleneck expects a 2D array")
    for col in range(arr.shape[1]):
        for row in range(window - 1, arr.shape[0]):
            out[row, col] = reducer(arr[row - window + 1: row + 1, col])
    return out


def move_rank(values, window, axis=0):
    if axis != 0:
        raise NotImplementedError("fallback move_rank only supports axis=0")

    def reducer(window_values):
        last = window_values[-1]
        finite = window_values[np.isfinite(window_values)]
        if not np.isfinite(last) or finite.size == 0:
            return np.nan
        if finite.size == 1:
            return 0.0
        less = np.sum(finite < last)
        equal = np.sum(finite == last)
        rank = less + (equal - 1) / 2.0
        return rank / (finite.size - 1) * 2.0 - 1.0

    return _window_result(values, window, reducer)


def move_argmax(values, window, axis=0):
    if axis != 0:
        raise NotImplementedError("fallback move_argmax only supports axis=0")
    return _window_result(values, window, lambda x: float(np.nanargmax(x)) if np.isfinite(x).any() else np.nan)


def move_argmin(values, window, axis=0):
    if axis != 0:
        raise NotImplementedError("fallback move_argmin only supports axis=0")
    return _window_result(values, window, lambda x: float(np.nanargmin(x)) if np.isfinite(x).any() else np.nan)
'''


def _load_formulas(code_dir: Path) -> dict[int, str]:
    path = code_dir / "formulas.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    formulas: dict[int, str] = {}
    for key, value in payload.items():
        if not key.lower().startswith("alpha"):
            continue
        try:
            alpha_id = int(key[5:])
        except ValueError:
            continue
        if isinstance(value, dict):
            formulas[alpha_id] = str(value.get("formula") or "")
        else:
            formulas[alpha_id] = str(value)
    return formulas


def _alpha_ids(limit: int | None, ids: str | None) -> list[int]:
    if ids:
        selected: list[int] = []
        for part in ids.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = part.split("-", 1)
                selected.extend(range(int(start), int(end) + 1))
            else:
                selected.append(int(part))
    else:
        selected = list(range(1, 192))
    selected = [alpha_id for alpha_id in selected if 1 <= alpha_id <= 191]
    if limit is not None and limit > 0:
        selected = selected[:limit]
    return selected


def _strategy_code(strategy_id: str, alpha_id: int, direction: str, formula: str) -> str:
    formula_literal = repr(formula)
    return f'''"""Temporary Alpha191 strategy alpha{alpha_id:03d} {direction}."""

from __future__ import annotations

from _alpha191_tsp_helper import Alpha191MatrixStrategy, build_meta

STRATEGY_ID = "{strategy_id}"
ALPHA_ID = {alpha_id}
DIRECTION = "{direction}"
FORMULA = {formula_literal}

META = build_meta(STRATEGY_ID, ALPHA_ID, DIRECTION, FORMULA)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{{STRATEGY_ID}}_top10"]
EXIT_SIGNALS = [f"signal_{{STRATEGY_ID}}_buffer15_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = Alpha191MatrixStrategy(STRATEGY_ID, ALPHA_ID, DIRECTION)
'''


def _prepare_temp_strategies(
    temp_dir: Path,
    code_dir: Path,
    rows: list[dict[str, Any]],
) -> None:
    alpha_code_dir = temp_dir / "_alpha191_code"
    alpha_code_dir.mkdir()
    for filename in (
        "operators.py",
        "engine.py",
        "alphas_001_050.py",
        "alphas_051_100.py",
        "alphas_101_150.py",
        "alphas_151_191.py",
    ):
        shutil.copy2(code_dir / filename, alpha_code_dir / filename)
    (temp_dir / "_alpha191_tsp_helper.py").write_text(HELPER_CODE, encoding="utf-8")
    if importlib.util.find_spec("bottleneck") is None:
        (alpha_code_dir / "bottleneck.py").write_text(BOTTLENECK_FALLBACK_CODE, encoding="utf-8")
    for row in rows:
        path = temp_dir / f"{row['strategy_id']}.py"
        path.write_text(
            _strategy_code(row["strategy_id"], row["alpha_id"], row["direction"], row.get("formula") or ""),
            encoding="utf-8",
        )


def _service(data_dir: Path, temp_strategy_dir: Path) -> StrategyBacktestService:
    store = DataStore(data_dir)
    repo = KlineRepository(store)
    from app.strategy.ai_generator import AIStrategyGenerator

    original_validate = AIStrategyGenerator._validate_safety
    AIStrategyGenerator._validate_safety = staticmethod(lambda code, **kwargs: None)
    try:
        strategy_engine = StrategyEngine(
            strategy_dirs=[
                BACKEND / "app" / "strategy" / "builtin",
                data_dir / "strategies" / "custom",
                data_dir / "strategies" / "ai",
                data_dir / "strategies" / "composite",
                temp_strategy_dir,
            ],
            override_loader=lambda sid: strategy_config.load_override(data_dir, sid),
        )
        errors = strategy_engine.load_errors()
        if errors:
            raise RuntimeError(f"strategy load errors: {errors}")
    finally:
        AIStrategyGenerator._validate_safety = original_validate
    return StrategyBacktestService(BacktestEngine(repo), strategy_engine)


def _backtest_config(strategy_id: str, args: argparse.Namespace) -> StrategyBacktestConfig:
    return StrategyBacktestConfig(
        strategy_id=strategy_id,
        symbols=None,
        start=args.start,
        end=args.end,
        params=dict(DEFAULT_PARAMS),
        overrides={},
        matching="open_t+1",
        entry_fill="open_t+1",
        exit_fill="open_t+1",
        commission_pct=0.0003,
        stamp_tax_pct=0.001,
        slippage_bps=10,
        max_positions=10,
        max_exposure_pct=args.max_exposure_pct,
        initial_capital=1_000_000.0,
        position_sizing="equal",
        mode="position",
        holding_days=5,
        asset_type="stock",
    )


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    stats = result.get("stats") or {}
    execution = stats.get("execution") or {}
    keys = (
        "total_return",
        "annual_return",
        "max_drawdown",
        "sharpe",
        "sortino",
        "calmar",
        "win_rate",
        "profit_factor",
        "n_trades",
        "final_equity",
        "execution_backend",
    )
    return {
        "run_id": result.get("run_id"),
        "error": result.get("error"),
        "elapsed_ms": result.get("elapsed_ms"),
        **{key: stats.get(key) for key in keys},
        "sell_suspended": execution.get("sell_suspended"),
        "buy_suspended": execution.get("buy_suspended"),
        "pending_exit": execution.get("pending_exit"),
        "pending_exit_positions": stats.get("pending_exit_positions"),
        "max_exposure": stats.get("max_exposure"),
        "avg_exposure": stats.get("avg_exposure"),
    }


def _score(row: dict[str, Any]) -> float:
    if row.get("error"):
        return -1e9
    total_return = float(row.get("total_return") or -1.0)
    sharpe = float(row.get("sharpe") or -10.0)
    max_drawdown = float(row.get("max_drawdown") or -1.0)
    pending_exit_positions = float(row.get("pending_exit_positions") or 0.0)
    return total_return + 0.25 * sharpe + 0.5 * max_drawdown - 0.01 * pending_exit_positions


def _best_by_alpha(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[int, dict[str, Any]] = {}
    for row in rows:
        alpha_id = row.get("alpha_id")
        if not isinstance(alpha_id, int):
            continue
        if alpha_id not in best or _score(row) > _score(best[alpha_id]):
            best[alpha_id] = row
    return sorted(best.values(), key=_score, reverse=True)


def _write_outputs(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = path.with_suffix(".csv")
    rows = report.get("rows") or []
    if not rows:
        return
    fieldnames = [
        "strategy_id",
        "alpha_id",
        "direction",
        "formula",
        "total_return",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "win_rate",
        "n_trades",
        "final_equity",
        "avg_exposure",
        "max_exposure",
        "pending_exit_positions",
        "elapsed_sec",
        "error",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _build_work_rows(args: argparse.Namespace, formulas: dict[int, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for alpha_id in _alpha_ids(args.limit, args.ids):
        for direction in args.directions:
            rows.append({
                "strategy_id": f"{args.prefix}_a{alpha_id:03d}_{direction}",
                "alpha_id": alpha_id,
                "direction": direction,
                "formula": formulas.get(alpha_id, ""),
            })
    return rows


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    code_dir = args.repo_code_dir
    if not (code_dir / "engine.py").exists():
        raise FileNotFoundError(f"missing Alpha191 code dir: {code_dir}")
    formulas = _load_formulas(code_dir)
    work_rows = _build_work_rows(args, formulas)
    if not work_rows:
        raise ValueError("no Alpha191 factors selected")

    existing_rows: list[dict[str, Any]] = []
    existing_baseline: dict[str, Any] | None = None
    if args.resume and args.output.exists() and args.output.stat().st_size > 0:
        existing_report = json.loads(args.output.read_text(encoding="utf-8"))
        existing_rows = list(existing_report.get("rows") or [])
        existing_baseline = existing_report.get("baseline")
    done_strategy_ids = {
        str(row.get("strategy_id"))
        for row in existing_rows
        if row.get("strategy_id")
    }
    pending_rows = [
        row for row in work_rows
        if row["strategy_id"] not in done_strategy_ids
    ]

    report: dict[str, Any] = {
        "repo_code_dir": str(code_dir),
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "params": dict(DEFAULT_PARAMS),
        "execution": {
            "matching": "open_t+1",
            "max_positions": 10,
            "max_exposure_pct": args.max_exposure_pct,
            "commission_pct": 0.0003,
            "stamp_tax_pct": 0.001,
            "slippage_bps": 10,
            "benchmark_proxy": "cross-sectional mean open/close; no external index series in TSP matrix",
        },
        "rows": existing_rows,
        "best_by_alpha": _best_by_alpha(existing_rows),
        "baseline": existing_baseline,
    }

    if done_strategy_ids:
        print(f"resume: skip {len(done_strategy_ids)} completed rows, run {len(pending_rows)} pending rows")
    if not pending_rows and (not args.include_baseline or existing_baseline is not None):
        report["rows"] = sorted(report["rows"], key=_score, reverse=True)
        report["best_by_alpha"] = _best_by_alpha(report["rows"])
        _write_outputs(args.output, report)
        return report

    with tempfile.TemporaryDirectory(prefix="tsp_alpha191_") as temp_name:
        temp_dir = Path(temp_name)
        _prepare_temp_strategies(temp_dir, code_dir, pending_rows)
        service = _service(args.data_dir, temp_dir)

        if args.include_baseline and existing_baseline is None:
            started = time.time()
            try:
                result = asdict(service.run(_backtest_config(BASELINE_STRATEGY_ID, args)))
                report["baseline"] = {
                    "strategy_id": BASELINE_STRATEGY_ID,
                    "elapsed_sec": round(time.time() - started, 2),
                    **_compact_result(result),
                }
            except Exception as exc:
                report["baseline"] = {
                    "strategy_id": BASELINE_STRATEGY_ID,
                    "elapsed_sec": round(time.time() - started, 2),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }

        for index, item in enumerate(pending_rows, 1):
            started = time.time()
            try:
                result = asdict(service.run(_backtest_config(item["strategy_id"], args)))
                row = {
                    **item,
                    "elapsed_sec": round(time.time() - started, 2),
                    **_compact_result(result),
                }
            except Exception as exc:
                row = {
                    **item,
                    "elapsed_sec": round(time.time() - started, 2),
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            row["live_like_score"] = _score(row)
            report["rows"].append(row)
            report["best_by_alpha"] = _best_by_alpha(report["rows"])
            _write_outputs(args.output, report)
            print(
                f"[{index}/{len(pending_rows)}] {item['strategy_id']}: "
                f"ret={row.get('total_return')} mdd={row.get('max_drawdown')} "
                f"sharpe={row.get('sharpe')} err={row.get('error')}"
            )

    report["rows"] = sorted(report["rows"], key=_score, reverse=True)
    report["best_by_alpha"] = _best_by_alpha(report["rows"])
    _write_outputs(args.output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-code-dir", type=Path, default=Path("/tmp/alpha191-oos-dashboard/code"))
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 10, 20))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 19))
    parser.add_argument("--limit", type=int, default=0, help="limit number of alpha ids; 0 means all")
    parser.add_argument("--ids", default=None, help="comma-separated ids/ranges, for example 1,5,10-20")
    parser.add_argument("--directions", nargs="+", choices=("high", "low"), default=["high", "low"])
    parser.add_argument("--prefix", default="tmp_alpha191_oos")
    parser.add_argument("--max-exposure-pct", type=float, default=0.6)
    parser.add_argument("--include-baseline", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp_alpha191_tsp_1y.json")
    args = parser.parse_args()
    if args.limit <= 0:
        args.limit = None

    report = evaluate(args)
    print(f"saved {len(report['rows'])} rows to {args.output}")
    print("top 20 best directions:")
    for row in report["rows"][:20]:
        print(
            f"alpha{row.get('alpha_id'):03d} {row.get('direction')} "
            f"ret={row.get('total_return')} sharpe={row.get('sharpe')} "
            f"mdd={row.get('max_drawdown')} trades={row.get('n_trades')}"
        )
    print("top 20 best by alpha:")
    for row in report["best_by_alpha"][:20]:
        print(
            f"alpha{row.get('alpha_id'):03d} {row.get('direction')} "
            f"ret={row.get('total_return')} sharpe={row.get('sharpe')} "
            f"mdd={row.get('max_drawdown')} trades={row.get('n_trades')}"
        )


if __name__ == "__main__":
    main()
