"""Low-crowding AlphaGPT variant: CV and MA60 repair jump."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_cv_bias_jump"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "MA60_BIAS_LOW",
    "MUL",
    "DECAY",
    "JUMP",
    "CA_CORR20_LOW",
    "MUL",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding CV bias jump",
    "Jump on the combined CV low-crowding and MA60 repair leg, then confirm with CA decoupling.",
    ["AlphaGPT", "low_crowding", "cv_bias_jump", "mean_repair", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
