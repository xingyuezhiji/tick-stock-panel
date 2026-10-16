"""Run a compact risk-control grid for AlphaGPT matrix-native strategies."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.backtest.engine import BacktestEngine
from app.backtest.strategy import StrategyBacktestConfig, StrategyBacktestService
from app.strategy import config as strategy_config
from app.strategy.engine import StrategyEngine
from app.tickflow.repository import DataStore, KlineRepository


DEFAULT_STRATEGIES = (
    "ai_alphagpt_round922_sharpe5",
    "ai_alphagpt_round930_vol_chg_jump",
)

GRID = (
    {"name": "baseline", "stop_loss": None, "trailing_stop": None, "max_positions": 30, "max_exposure_pct": 1.0},
    {"name": "stop8_exp80", "stop_loss": -0.08, "trailing_stop": None, "max_positions": 30, "max_exposure_pct": 0.8},
    {"name": "stop10_exp100", "stop_loss": -0.10, "trailing_stop": None, "max_positions": 30, "max_exposure_pct": 1.0},
    {"name": "trail10_exp80", "stop_loss": None, "trailing_stop": 0.10, "max_positions": 30, "max_exposure_pct": 0.8},
    {"name": "stop10_trail10_exp80", "stop_loss": -0.10, "trailing_stop": 0.10, "max_positions": 30, "max_exposure_pct": 0.8},
    {"name": "stop8_trail10_exp60_pos20", "stop_loss": -0.08, "trailing_stop": 0.10, "max_positions": 20, "max_exposure_pct": 0.6},
    {"name": "stop10_trail12_exp60_pos20", "stop_loss": -0.10, "trailing_stop": 0.12, "max_positions": 20, "max_exposure_pct": 0.6},
    {"name": "stop10_trail12_exp50_pos5", "stop_loss": -0.10, "trailing_stop": 0.12, "max_positions": 5, "max_exposure_pct": 0.5},
)


def _service(data_dir: Path) -> StrategyBacktestService:
    store = DataStore(data_dir)
    repo = KlineRepository(store)
    strategy_engine = StrategyEngine(
        strategy_dirs=[
            BACKEND / "app" / "strategy" / "builtin",
            data_dir / "strategies" / "custom",
            data_dir / "strategies" / "ai",
            data_dir / "strategies" / "composite",
        ],
        override_loader=lambda sid: strategy_config.load_override(data_dir, sid),
    )
    return StrategyBacktestService(BacktestEngine(repo), strategy_engine)


def _stats(result: dict) -> dict:
    stats = result.get("stats") or {}
    out = {
        "run_id": result.get("run_id"),
        "error": result.get("error"),
        "elapsed_ms": result.get("elapsed_ms"),
    }
    for key in (
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
        "max_exposure",
        "execution_backend",
    ):
        out[key] = stats.get(key)
    return out


def run_grid(args: argparse.Namespace) -> list[dict]:
    service = _service(args.data_dir)
    rows: list[dict] = []
    for strategy_id in args.strategy:
        for item in GRID:
            overrides = {}
            if item["stop_loss"] is not None:
                overrides["stop_loss"] = item["stop_loss"]
            if item["trailing_stop"] is not None:
                overrides["trailing_stop"] = item["trailing_stop"]
            cfg = StrategyBacktestConfig(
                strategy_id=strategy_id,
                symbols=None,
                start=args.start,
                end=args.end,
                params={
                    "n_buy": 30,
                    "n_hold": 45,
                    "min_listed_days": 60,
                    "amount_window": 20,
                    "min_avg_amount": 30_000_000.0,
                },
                overrides=overrides,
                matching="open_t+1",
                entry_fill="open_t+1",
                exit_fill="open_t+1",
                commission_pct=0.0003,
                stamp_tax_pct=0.001,
                slippage_bps=10,
                max_positions=item["max_positions"],
                max_exposure_pct=item["max_exposure_pct"],
                initial_capital=1_000_000.0,
                position_sizing="equal",
                mode="position",
                holding_days=5,
                asset_type="stock",
            )
            started = time.time()
            result = asdict(service.run(cfg))
            row = {
                "strategy_id": strategy_id,
                "grid": item["name"],
                "risk": item,
                "elapsed_sec": round(time.time() - started, 2),
                **_stats(result),
            }
            rows.append(row)
            print(
                f"{strategy_id} {item['name']}: "
                f"ret={row.get('total_return')} mdd={row.get('max_drawdown')} "
                f"sharpe={row.get('sharpe')} err={row.get('error')}"
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 9, 30))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--strategy", action="append", choices=None, default=list(DEFAULT_STRATEGIES))
    parser.add_argument("--output", type=Path, default=ROOT / "tmp_alphagpt_risk_grid.json")
    args = parser.parse_args()

    rows = run_grid(args)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
