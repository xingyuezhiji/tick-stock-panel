"""Low-crowding mean-repair AlphaGPT variant: delayed confirmation."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_delay_confirm"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "DELAY1",
    "CA_CORR20_LOW",
    "DELAY1",
    "MUL",
    "MA60_BIAS_LOW",
    "MUL",
    "DECAY",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding delay confirm",
    "Require yesterday's low crowding structure before combining with current MA60 repair.",
    ["AlphaGPT", "low_crowding", "mean_repair", "delay_confirm", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
