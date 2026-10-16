"""AlphaGPT round922 high-Sharpe candidate #3."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round922_sharpe3"
FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "CA_CORR20_LOW",
    "MA60_BIAS_LOW",
    "MUL",
    "CA_CORR20_LOW",
    "MA60_BIAS_LOW",
    "GATE",
    "DECAY",
    "DELAY1",
    "MUL",
    "DECAY",
    "JUMP",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT Round922 高Sharpe候选3",
    "参考中低收益候选1结构挖掘, AlphaGPT account reward Sharpe 2.21",
    ["AlphaGPT", "Round922", "高Sharpe", "候选1相似", "A股因子", "周度轮动"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
