"""Low-crowding AlphaGPT variant: MA60 repair jump core."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_bias_jump_core"
FORMULA_TOKENS = (
    "MA60_BIAS_LOW",
    "JUMP",
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "MUL",
    "MUL",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding bias jump core",
    "MA60 repair jump confirmed by low price-volume and price-amount crowding.",
    ["AlphaGPT", "low_crowding", "mean_repair", "jump", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
