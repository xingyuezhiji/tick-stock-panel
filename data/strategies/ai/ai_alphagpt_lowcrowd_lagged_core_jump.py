"""Low-crowding AlphaGPT variant: lagged core jump."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_lagged_core_jump"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "MUL",
    "MA60_BIAS_LOW",
    "MUL",
    "DECAY",
    "JUMP",
    "DELAY1",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding lagged core jump",
    "Use yesterday's low-crowding repair jump to avoid same-day spike chasing.",
    ["AlphaGPT", "low_crowding", "mean_repair", "lagged_jump", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
