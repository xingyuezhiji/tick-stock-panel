"""Low-crowding AlphaGPT variant: gate jump with correlation product confirmation."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_gate_jump_corr_confirm"
FORMULA_TOKENS = (
    "MA60_BIAS_LOW",
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "GATE",
    "DECAY",
    "JUMP",
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "MUL",
    "MUL",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding gate jump corr confirm",
    "Gated low-crowding jump confirmed by the product of CV and CA low-crowding scores.",
    ["AlphaGPT", "low_crowding", "gate", "jump", "corr_confirm", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
