"""AlphaGPT round935 candidate #1: low-crowding gated max3."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round935_c01_gate_max3"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "MA60_BIAS_LOW",
    "MA60_BIAS_LOW",
    "CA_CORR20_LOW",
    "GATE",
    "CV_CORR30_LOW",
    "MAX3",
    "GATE",
    "MA60_BIAS_LOW",
    "GATE",
    "MAX3",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round935 c01 gate max3",
    "Round935 top AlphaGPT formula using low crowding, MA60 repair gating, and MAX3 smoothing.",
    ["AlphaGPT", "round935", "low_crowding", "mean_repair", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
