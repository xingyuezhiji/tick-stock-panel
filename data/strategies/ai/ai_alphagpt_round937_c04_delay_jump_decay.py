"""AlphaGPT round937 candidate #4: delayed decay jump."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round937_c04_delay_jump_decay"
FORMULA_TOKENS = (
    "CA_CORR20_LOW",
    "CV_CORR30_LOW",
    "DECAY",
    "DELAY1",
    "JUMP",
    "MA60_BIAS_LOW",
    "DECAY",
    "MUL",
    "DECAY",
    "DECAY",
    "MAX3",
    "MUL",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round937 c04 delay jump decay",
    "Round937 AlphaGPT formula delaying decayed low-crowding jump and pairing it with MA60 repair.",
    ["AlphaGPT", "round937", "low_crowding", "mean_repair", "jump", "delay", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
