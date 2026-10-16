"""AlphaGPT round937 candidate #5: correlation ratio decay."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round937_c05_corr_ratio_decay"
FORMULA_TOKENS = (
    "CA_CORR20_LOW",
    "DECAY",
    "CV_CORR30_LOW",
    "JUMP",
    "CV_CORR30_LOW",
    "DIV",
    "CV_CORR30_LOW",
    "DIV",
    "MA60_BIAS_LOW",
    "DECAY",
    "DIV",
    "MUL",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round937 c05 corr ratio decay",
    "Round937 AlphaGPT formula using low-crowding correlation ratios with MA60 repair decay.",
    ["AlphaGPT", "round937", "low_crowding", "mean_repair", "jump", "ratio", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
