"""AlphaGPT round935 candidate #5: decay gate."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round935_c05_decay_gate"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "MA60_BIAS_LOW",
    "MA60_BIAS_LOW",
    "MA60_BIAS_LOW",
    "CA_CORR20_LOW",
    "NEG",
    "DECAY",
    "GATE",
    "CA_CORR20_LOW",
    "GATE",
    "CA_CORR20_LOW",
    "GATE",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round935 c05 decay gate",
    "Round935 AlphaGPT formula using delayed decay of the low-crowding and MA60 repair branches.",
    ["AlphaGPT", "round935", "low_crowding", "mean_repair", "decay", "weekly_rotation"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
