"""AlphaGPT round944 candidate #1: decayed low-crowding confirmation."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round944_c01_decay_cv_delay"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "DECAY",
    "MA60_BIAS_LOW",
    "CV_CORR30_LOW",
    "CV_CORR30_LOW",
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
    "AlphaGPT round944 c01 decay cv delay",
    "Round944 two-year mutation using decayed low price-volume crowding with MA60 bias confirmation.",
    ["AlphaGPT", "round944", "low_crowding", "decay", "jump", "weekly_rotation"],
)
META["params"][0]["default"] = 10
META["params"][1]["default"] = 15
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
