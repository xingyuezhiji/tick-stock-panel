"""Low-crowding mean-repair AlphaGPT variant: smoothed core."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_core_decay"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "MUL",
    "MA60_BIAS_LOW",
    "MUL",
    "DECAY",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding core decay",
    "Low price-volume/price-amount coupling with MA60 pullback repair, smoothed by decay.",
    ["AlphaGPT", "low_crowding", "mean_repair", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
