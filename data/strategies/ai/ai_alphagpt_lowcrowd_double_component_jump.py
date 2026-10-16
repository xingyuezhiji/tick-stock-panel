"""Low-crowding AlphaGPT variant: double component jump."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_double_component_jump"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "JUMP",
    "CA_CORR20_LOW",
    "JUMP",
    "MUL",
    "MA60_BIAS_LOW",
    "MUL",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding double component jump",
    "Require simultaneous jumps in CV and CA low-crowding components before MA60 repair.",
    ["AlphaGPT", "low_crowding", "component_jump", "mean_repair", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
