"""Low-crowding mean-repair AlphaGPT variant: repaired jump."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_core_jump"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "MUL",
    "MA60_BIAS_LOW",
    "MUL",
    "DECAY",
    "JUMP",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding core jump",
    "Low crowding and MA60 repair core, keeping only recent positive score jumps.",
    ["AlphaGPT", "low_crowding", "mean_repair", "jump", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
