"""AlphaGPT round937 candidate #1: low-correlation MA60 jump product."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round937_c01_lowcorr_ma60_jump"
FORMULA_TOKENS = (
    "CA_CORR20_LOW",
    "CA_CORR20_LOW",
    "MA60_BIAS_LOW",
    "MUL",
    "MA60_BIAS_LOW",
    "MUL",
    "MUL",
    "MAX3",
    "DELAY1",
    "CV_CORR30_LOW",
    "JUMP",
    "MUL",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round937 c01 lowcorr ma60 jump",
    "Round937 AlphaGPT formula combining low price-amount crowding, MA60 repair, and delayed volume-correlation jump.",
    ["AlphaGPT", "round937", "low_crowding", "mean_repair", "jump", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
