"""AlphaGPT round927 high-Sharpe candidate #6."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round927_highsharpe6"
FORMULA_TOKENS = (
    "RSV",
    "RSV",
    "RSV",
    "VWAP_DEV",
    "MAX3",
    "SUB",
    "SUB",
    "MAX3",
    "SUB",
    "MAX3",
    "MAX3",
    "MAX3",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT Round927 高Sharpe候选6",
    "19因子自由挖掘, AlphaGPT account reward Sharpe 2.90",
    ["AlphaGPT", "Round927", "高Sharpe", "19因子", "A股因子", "周度轮动"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
