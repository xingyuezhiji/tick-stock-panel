"""Low-crowding mean-repair AlphaGPT variant: correlation gate."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_gate_corr"
FORMULA_TOKENS = (
    "CA_CORR20_LOW",
    "MA60_BIAS_LOW",
    "CV_CORR30_LOW",
    "GATE",
    "DECAY",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding gate corr",
    "Use low price-amount coupling as the gate between MA60 pullback and low CV correlation.",
    ["AlphaGPT", "low_crowding", "mean_repair", "gate", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
