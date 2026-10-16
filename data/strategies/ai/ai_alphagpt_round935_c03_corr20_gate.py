"""AlphaGPT round935 candidate #3: corr20 confirmation gate."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round935_c03_corr20_gate"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "MA60_BIAS_LOW",
    "CA_CORR20_LOW",
    "NEG",
    "CA_CORR20_LOW",
    "ADD",
    "MA60_BIAS_LOW",
    "ADD",
    "CV_CORR20_LOW",
    "GATE",
    "MA60_BIAS_LOW",
    "GATE",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round935 c03 corr20 gate",
    "Round935 AlphaGPT formula with CV30/CA20 low-crowding core and CV20 confirmation gating.",
    ["AlphaGPT", "round935", "low_crowding", "mean_repair", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
