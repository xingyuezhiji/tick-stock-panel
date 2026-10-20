"""AlphaGPT round943 candidate #3: max crowding CV gate."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round943_c03_max_cv_gate"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "MAX3",
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
    "AlphaGPT round943 c03 max cv gate",
    "Round943 c12 mutation using three-day low-crowding confirmation and CV jump gating.",
    ["AlphaGPT", "round943", "low_crowding", "max3", "jump", "weekly_rotation"],
)
META["params"][0]["default"] = 10
META["params"][1]["default"] = 15
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
