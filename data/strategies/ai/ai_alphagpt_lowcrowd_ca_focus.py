"""Low-crowding mean-repair AlphaGPT variant: CA focus."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_ca_focus"
FORMULA_TOKENS = (
    "CA_CORR20_LOW",
    "MA60_BIAS_LOW",
    "MUL",
    "DECAY",
    "CV_CORR30_LOW",
    "MUL",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding CA focus",
    "Start from low price-amount coupling and MA60 repair, then confirm with low CV correlation.",
    ["AlphaGPT", "low_crowding", "mean_repair", "ca_focus", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
