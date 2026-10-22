"""Evaluate AlphaGPT RPN candidates with the TSP live-like backtest settings."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
AI_DIR = ROOT / "data" / "strategies" / "ai"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.backtest.engine import BacktestEngine
from app.backtest.strategy import StrategyBacktestConfig, StrategyBacktestService
from app.strategy import config as strategy_config
from app.strategy.engine import StrategyEngine
from app.tickflow.repository import DataStore, KlineRepository


BASELINE_STRATEGY_ID = "ai_alphagpt_round935_c12_jump_delay"
DEFAULT_PARAMS = {
    "n_buy": 10,
    "n_hold": 15,
    "min_listed_days": 60,
    "amount_window": 20,
    "min_avg_amount": 30_000_000.0,
}


def _load_candidates(path: Path, limit: int) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_candidates = payload.get("top_candidates") or []
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        formula = str(candidate.get("formula") or "").strip()
        if not formula or formula in seen:
            continue
        seen.add(formula)
        tokens = tuple(part for part in formula.split() if part)
        if not tokens:
            continue
        candidates.append({
            "rank": len(candidates) + 1,
            "formula": formula,
            "tokens": tokens,
            "alphagpt_score": candidate.get("score"),
            "alphagpt_metrics": candidate.get("metrics") or {},
        })
        if len(candidates) >= limit:
            break
    return candidates


def _strategy_code(strategy_id: str, tokens: tuple[str, ...], rank: int) -> str:
    token_lines = "\n".join(f'    "{token}",' for token in tokens)
    return f'''"""Temporary AlphaGPT candidate #{rank} for live-like TSP evaluation."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "{strategy_id}"
FORMULA_TOKENS = (
{token_lines}
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT temp candidate {rank}",
    "Temporary AlphaGPT candidate evaluated with TSP live-like settings.",
    ["AlphaGPT", "temporary", "live_like_screen"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{{STRATEGY_ID}}_top30"]
EXIT_SIGNALS = [f"signal_{{STRATEGY_ID}}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
'''


def _prepare_temp_strategies(temp_dir: Path, candidates: list[dict[str, Any]], prefix: str) -> None:
    shutil.copy2(AI_DIR / "_alphagpt_formula_helper.py", temp_dir / "_alphagpt_formula_helper.py")
    for candidate in candidates:
        strategy_id = f"{prefix}_c{candidate['rank']:02d}"
        candidate["strategy_id"] = strategy_id
        path = temp_dir / f"{strategy_id}.py"
        path.write_text(
            _strategy_code(strategy_id, candidate["tokens"], candidate["rank"]),
            encoding="utf-8",
        )


def _service(data_dir: Path, temp_strategy_dir: Path) -> StrategyBacktestService:
    store = DataStore(data_dir)
    repo = KlineRepository(store)
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
    sell_suspended = float(row.get("sell_suspended") or 0.0)
    pending_exit_positions = float(row.get("pending_exit_positions") or 0.0)
    return total_return + 0.25 * sharpe + 0.5 * max_drawdown - 0.01 * pending_exit_positions - 0.0001 * sell_suspended


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    candidates = _load_candidates(args.input, args.limit)
    if not candidates:
        raise ValueError(f"no candidates found in {args.input}")

    with tempfile.TemporaryDirectory(prefix="tsp_alphagpt_") as temp_name:
        temp_dir = Path(temp_name)
        _prepare_temp_strategies(temp_dir, candidates, args.prefix)
        service = _service(args.data_dir, temp_dir)

        rows: list[dict[str, Any]] = []
        strategy_ids = [BASELINE_STRATEGY_ID] + [str(candidate["strategy_id"]) for candidate in candidates]
        candidate_by_id = {str(candidate["strategy_id"]): candidate for candidate in candidates}
        for strategy_id in strategy_ids:
            started = time.time()
            result = asdict(service.run(_backtest_config(strategy_id, args)))
            row = {
                "strategy_id": strategy_id,
                "elapsed_sec": round(time.time() - started, 2),
                **_compact_result(result),
            }
            if strategy_id in candidate_by_id:
                candidate = candidate_by_id[strategy_id]
                row.update({
                    "rank": candidate["rank"],
                    "formula": candidate["formula"],
                    "alphagpt_score": candidate["alphagpt_score"],
                    "alphagpt_metrics": candidate["alphagpt_metrics"],
                })
            rows.append(row)
            print(
                f"{strategy_id}: ret={row.get('total_return')} "
                f"mdd={row.get('max_drawdown')} sharpe={row.get('sharpe')} "
                f"sell_sus={row.get('sell_suspended')} pending_pos={row.get('pending_exit_positions')} "
                f"err={row.get('error')}"
            )

    baseline = rows[0]
    candidate_rows = rows[1:]
    baseline_return = float(baseline.get("total_return") or 0.0)
    baseline_sharpe = float(baseline.get("sharpe") or 0.0)
    for row in candidate_rows:
        row["delta_return_vs_c12"] = None if row.get("total_return") is None else float(row["total_return"]) - baseline_return
        row["delta_sharpe_vs_c12"] = None if row.get("sharpe") is None else float(row["sharpe"]) - baseline_sharpe
        row["live_like_score"] = _score(row)

    return {
        "input": str(args.input),
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "params": dict(DEFAULT_PARAMS),
        "execution": {
            "matching": "open_t+1",
            "max_positions": 10,
            "max_exposure_pct": args.max_exposure_pct,
            "stop_loss": None,
            "trailing_stop": None,
        },
        "baseline": baseline,
        "candidates": sorted(candidate_rows, key=_score, reverse=True),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 9, 30))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--prefix", default="tmp_alphagpt_round942")
    parser.add_argument("--max-exposure-pct", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp_alphagpt_candidate_screen.json")
    args = parser.parse_args()

    report = evaluate(args)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(report['candidates'])} candidates to {args.output}")
    print("top 10:")
    for row in report["candidates"][:10]:
        print(
            f"#{row.get('rank')} {row['strategy_id']} "
            f"ret={row.get('total_return')} mdd={row.get('max_drawdown')} "
            f"sharpe={row.get('sharpe')} delta_ret={row.get('delta_return_vs_c12')}"
        )


if __name__ == "__main__":
    main()
