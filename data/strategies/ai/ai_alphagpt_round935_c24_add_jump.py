"""AlphaGPT round935 candidate #24: additive jump gate."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round935_c24_add_jump"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "MA60_BIAS_LOW",
    "CA_CORR20_LOW",
    "MA60_BIAS_LOW",
    "ADD",
    "MA60_BIAS_LOW",
    "GATE",
    "MAX3",
    "MAX3",
    "CA_CORR20_LOW",
    "GATE",
    "JUMP",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round935 c24 add jump",
    "Round935 AlphaGPT formula using an additive MA60 repair branch followed by jump filtering.",
    ["AlphaGPT", "round935", "low_crowding", "mean_repair", "jump", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
