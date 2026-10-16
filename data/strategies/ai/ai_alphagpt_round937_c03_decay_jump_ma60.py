"""AlphaGPT round937 candidate #3: decay jump MA60 product."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round937_c03_decay_jump_ma60"
FORMULA_TOKENS = (
    "CA_CORR20_LOW",
    "CV_CORR30_LOW",
    "DECAY",
    "JUMP",
    "MA60_BIAS_LOW",
    "MUL",
    "MA60_BIAS_LOW",
    "MUL",
    "DECAY",
    "DECAY",
    "DECAY",
    "MUL",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round937 c03 decay jump ma60",
    "Round937 AlphaGPT formula using decayed low-crowding jump confirmations with repeated MA60 repair exposure.",
    ["AlphaGPT", "round937", "low_crowding", "mean_repair", "jump", "decay", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
