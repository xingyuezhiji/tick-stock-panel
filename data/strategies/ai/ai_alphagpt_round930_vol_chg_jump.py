"""AlphaGPT round930 liquidity-constrained candidate based on VOL_CHG jumps."""

from __future__ import annotations

from _alphagpt_formula_helper import AlphaGPTFormulaMatrixStrategy, build_meta

STRATEGY_ID = "ai_alphagpt_round930_vol_chg_jump"
FORMULA_TOKENS = (
    "VOL_CHG",
    "JUMP",
    "JUMP",
    "JUMP",
    "JUMP",
    "JUMP",
    "JUMP",
    "JUMP",
    "JUMP",
    "JUMP",
    "JUMP",
    "MAX3",
)

META = build_meta(
    STRATEGY_ID,
    "AlphaGPT Round930 VOL_CHG跳变候选",
    "19因子搜索空间 + 流动性约束下的 round930 高收益候选；训练口径回撤较高，需配合风控回测。",
    ["AlphaGPT", "Round930", "VOL_CHG", "流动性约束", "A股因子", "周度轮动"],
)
EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = [f"signal_{STRATEGY_ID}_top30"]
EXIT_SIGNALS = [f"signal_{STRATEGY_ID}_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None
MATRIX_STRATEGY = AlphaGPTFormulaMatrixStrategy(STRATEGY_ID, FORMULA_TOKENS)
