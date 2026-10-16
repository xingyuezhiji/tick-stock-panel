"""Low-crowding AlphaGPT variant: gate then jump."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_gate_then_jump"
FORMULA_TOKENS = (
    "MA60_BIAS_LOW",
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "GATE",
    "DECAY",
    "JUMP",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding gate then jump",
    "Gate CV versus CA low-crowding by MA60 repair, then keep only fresh jumps.",
    ["AlphaGPT", "low_crowding", "gate", "jump", "mean_repair", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
