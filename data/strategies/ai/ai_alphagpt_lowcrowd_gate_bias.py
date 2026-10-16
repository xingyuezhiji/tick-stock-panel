"""Low-crowding mean-repair AlphaGPT variant: MA60 bias gate."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_lowcrowd_gate_bias"
FORMULA_TOKENS = (
    "MA60_BIAS_LOW",
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "GATE",
    "DECAY",
    "DECAY",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT low crowding gate bias",
    "Use MA60 pullback as the gate between low CV correlation and low CA correlation.",
    ["AlphaGPT", "low_crowding", "mean_repair", "gate", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
