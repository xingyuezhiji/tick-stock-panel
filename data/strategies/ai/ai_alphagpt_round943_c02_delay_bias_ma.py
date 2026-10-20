"""AlphaGPT round943 candidate #2: delayed bias with MA jump gate."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round943_c02_delay_bias_ma"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "DELAY1",
    "MA60_BIAS_LOW",
    "CV_CORR30_LOW",
    "MA60_BIAS_LOW",
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
    "AlphaGPT round943 c02 delay bias ma",
    "Round943 c12 mutation combining delayed crowding with MA60 bias jump rejection.",
    ["AlphaGPT", "round943", "low_crowding", "mean_repair", "delay", "weekly_rotation"],
)
META["params"][0]["default"] = 10
META["params"][1]["default"] = 15
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
