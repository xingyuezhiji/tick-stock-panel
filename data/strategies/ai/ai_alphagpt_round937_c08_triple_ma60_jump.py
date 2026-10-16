"""AlphaGPT round937 candidate #8: triple MA60 jump."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round937_c08_triple_ma60_jump"
FORMULA_TOKENS = (
    "CA_CORR20_LOW",
    "CV_CORR30_LOW",
    "JUMP",
    "MA60_BIAS_LOW",
    "MUL",
    "MA60_BIAS_LOW",
    "MA60_BIAS_LOW",
    "MUL",
    "MUL",
    "MUL",
    "DECAY",
    "MAX3",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round937 c08 triple ma60 jump",
    "Round937 AlphaGPT formula emphasizing triple MA60 repair under low-crowding jump confirmation.",
    ["AlphaGPT", "round937", "low_crowding", "mean_repair", "jump", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
