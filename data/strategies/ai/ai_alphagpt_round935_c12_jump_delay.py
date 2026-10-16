"""AlphaGPT round935 candidate #12: jump with delayed gate."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round935_c12_jump_delay"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "MAX3",
    "MA60_BIAS_LOW",
    "CA_CORR20_LOW",
    "MA60_BIAS_LOW",
    "JUMP",
    "NEG",
    "GATE",
    "CV_CORR30_LOW",
    "DELAY1",
    "GATE",
    "JUMP",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round935 c12 jump delay",
    "Round935 AlphaGPT formula preserving only delayed low-crowding jump confirmations.",
    ["AlphaGPT", "round935", "low_crowding", "mean_repair", "jump", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
