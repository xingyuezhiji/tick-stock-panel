"""AlphaGPT round927 high-Sharpe candidate #1."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round927_highsharpe1"
FORMULA_TOKENS = (
    "RSV",
    "RSV",
    "RSV",
    "MUL",
    "JUMP",
    "RSV",
    "JUMP",
    "SUB",
    "SUB",
    "VWAP_DEV",
    "SUB",
    "MAX3",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT Round927 高Sharpe候选1",
    "19因子自由挖掘, AlphaGPT account reward Sharpe 3.08",
    ["AlphaGPT", "Round927", "高Sharpe", "19因子", "A股因子", "周度轮动"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
