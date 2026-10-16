"""Low-crowding AlphaGPT variant: CA jump core."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_ca_jump_core"
FORMULA_TOKENS = (
    "CA_CORR20_LOW",
    "JUMP",
    "CV_CORR30_LOW",
    "MUL",
    "MA60_BIAS_LOW",
    "MUL",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding CA jump core",
    "Jump in low price-amount crowding, confirmed by low CV correlation and MA60 repair.",
    ["AlphaGPT", "low_crowding", "ca_jump", "mean_repair", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
