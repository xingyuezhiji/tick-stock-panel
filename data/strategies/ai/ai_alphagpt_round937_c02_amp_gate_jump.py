"""AlphaGPT round937 candidate #2: amplitude gate jump."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round937_c02_amp_gate_jump"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "DECAY",
    "MA60_BIAS_LOW",
    "CA_CORR20_LOW",
    "DELAY1",
    "ABS",
    "ADD",
    "AMP20_LOW",
    "JUMP",
    "GATE",
    "DECAY",
    "JUMP",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT round937 c02 amp gate jump",
    "Round937 AlphaGPT formula gating MA60 repair and delayed low-crowding by low-amplitude jump confirmation.",
    ["AlphaGPT", "round937", "low_crowding", "mean_repair", "amplitude", "gate", "jump"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
