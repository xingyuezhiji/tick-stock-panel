"""AlphaGPT round944 candidate #2: delayed crowding with max3 fallback."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round944_c02_delay_cv_max3"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "DELAY1",
    "MA60_BIAS_LOW",
    "CV_CORR30_LOW",
    "CV_CORR30_LOW",
    "JUMP",
    "NEG",
    "GATE",
    "CV_CORR30_LOW",
    "MAX3",
    "GATE",
    "JUMP",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round944 c02 delay cv max3",
    "Round944 two-year mutation using delayed low crowding and max3 crowding fallback for lower drawdown.",
    ["AlphaGPT", "round944", "low_crowding", "max3", "jump", "weekly_rotation"],
)
META["params"][0]["default"] = 10
META["params"][1]["default"] = 15
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
