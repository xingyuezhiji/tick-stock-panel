"""G02 量价低相关周度轮动: matrix-native top30/buffer45."""

from __future__ import annotations

from datetime import date

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    _matrix_rolling_corr,
    make_signal_matrix,
    valid_rolling_mean,
)

META: dict = {
    "id": "ai_muzcgqf1",
    "name": "G02",
    "description": "30日收盘价-成交量相关系数最低股票, 每周Top30买入, Top45持有缓冲",
    "tags": ["拥挤度", "G02", "周度轮动", "截面排名", "量价"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "basic_filter": {"enabled": False},
    "params": [
        {"id": "corr_window", "label": "相关系数窗口(日)", "type": "int", "default": 30, "min": 5, "max": 120, "step": 1},
        {"id": "n_buy", "label": "买入前N名", "type": "int", "default": 30, "min": 5, "max": 200, "step": 1},
        {"id": "n_hold", "label": "持有缓冲前N名", "type": "int", "default": 45, "min": 5, "max": 300, "step": 1},
        {"id": "min_listed_days", "label": "上市观察交易日", "type": "int", "default": 60, "min": 20, "max": 250, "step": 1},
        {"id": "amount_window", "label": "成交额均线窗口", "type": "int", "default": 20, "min": 5, "max": 120, "step": 1},
        {"id": "min_avg_amount", "label": "最低平均成交额", "type": "float", "default": 30000000.0, "min": 0.0, "max": 1000000000.0, "step": 1000000.0},
        {"id": "ma_window", "label": "趋势均线窗口", "type": "int", "default": 60, "min": 5, "max": 250, "step": 1},
        {"id": "use_ma_filter", "label": "要求收盘价在均线上", "type": "bool", "default": True},
    ],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 45,
    "rebalance": {"mode": "equal_weight"},
    "stop_loss": None,
    "max_hold_days": None,
    "research_only": False,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_g02_weekly_top30"]
EXIT_SIGNALS = ["signal_g02_buffer45_exit"]
STOP_LOSS = None
MAX_HOLD_DAYS = None


def _int_param(params: dict, name: str, default: int, minimum: int) -> int:
    try:
        value = int(params.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _float_param(params: dict, name: str, default: float, minimum: float) -> float:
    try:
        value = float(params.get(name, default))
    except (TypeError, ValueError):
        value = default
    if not np.isfinite(value):
        return default
    return max(minimum, value)


def _first_trading_day_signal_mask(labels: tuple[str, ...]) -> np.ndarray:
    """Return signal rows whose next trading day is the first session of a week."""
    out = np.zeros(len(labels), dtype=bool)
    if len(labels) < 2:
        return out
    weeks = [date.fromisoformat(label[:10]).isocalendar()[:2] for label in labels]
    for time_id in range(len(labels) - 1):
        if weeks[time_id + 1] != weeks[time_id]:
            out[time_id] = True
    return out


def _top_rank_mask(eligible: np.ndarray, value: np.ndarray, top_n: int) -> np.ndarray:
    result = np.zeros(eligible.shape, dtype=bool)
    for time_id in range(eligible.shape[0]):
        asset_ids = np.flatnonzero(eligible[time_id] & np.isfinite(value[time_id]))
        if asset_ids.size == 0:
            continue
        selected = asset_ids[np.argsort(value[time_id, asset_ids], kind="stable")[:top_n]]
        result[time_id, selected] = True
    return result


def _low_value_score(eligible: np.ndarray, value: np.ndarray) -> np.ndarray:
    score = np.zeros(value.shape, dtype=np.float32)
    for time_id in range(value.shape[0]):
        asset_ids = np.flatnonzero(eligible[time_id] & np.isfinite(value[time_id]))
        count = asset_ids.size
        if count == 0:
            continue
        order = asset_ids[np.argsort(value[time_id, asset_ids], kind="stable")]
        if count == 1:
            score[time_id, order[0]] = np.float32(100.0)
            continue
        ranks = np.arange(count, dtype=np.float32)
        score[time_id, order] = (np.float32(1.0) - ranks / np.float32(count - 1)) * np.float32(100.0)
    return score


class G02WeeklyRotationMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "close", "volume", "amount"})

    def required_warmup_bars(self, params: dict) -> int:
        corr_window = _int_param(params, "corr_window", 30, 5)
        amount_window = _int_param(params, "amount_window", 20, 1)
        ma_window = _int_param(params, "ma_window", 60, 1)
        min_listed = _int_param(params, "min_listed_days", 60, 1)
        return max(corr_window, amount_window, ma_window, min_listed) + 5

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        corr_window = _int_param(params, "corr_window", 30, 5)
        n_buy = _int_param(params, "n_buy", 30, 1)
        n_hold = max(n_buy, _int_param(params, "n_hold", 45, 1))
        min_listed = _int_param(params, "min_listed_days", 60, 1)
        amount_window = _int_param(params, "amount_window", 20, 1)
        min_avg_amount = _float_param(params, "min_avg_amount", 30_000_000.0, 0.0)
        ma_window = _int_param(params, "ma_window", 60, 1)
        use_ma_filter = bool(params.get("use_ma_filter", True))

        valid = (
            np.isfinite(market.close)
            & np.isfinite(market.open)
            & (market.close > 0)
            & (market.open > 0)
            & np.isfinite(market.volume)
            & (market.volume > 0)
        )
        amount = market.field("amount")
        amount_valid = np.isfinite(amount) & (amount > 0)
        avg_amount = valid_rolling_mean(amount, valid & amount_valid, amount_window)
        ma = valid_rolling_mean(market.close, valid, ma_window)
        listed_days = np.cumsum(valid, axis=0)
        g02 = _matrix_rolling_corr(market.close, market.volume, valid, corr_window)

        eligible = (
            valid
            & amount_valid
            & np.isfinite(g02)
            & (listed_days >= min_listed)
            & np.isfinite(avg_amount)
            & (avg_amount >= min_avg_amount)
        )
        if use_ma_filter:
            eligible &= np.isfinite(ma) & (market.close > ma)

        score = _low_value_score(eligible, g02)
        signal_days = _first_trading_day_signal_mask(market.timestamp_labels)
        buy_pool = _top_rank_mask(eligible, g02, n_buy)
        buffer_pool = _top_rank_mask(eligible, g02, n_hold)

        entry = buy_pool & signal_days[:, None]
        exit_ = (~buffer_pool) & signal_days[:, None]
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_g02_weekly_top30",),
            exit_signal_ids=("signal_g02_buffer45_exit",),
        )


MATRIX_STRATEGY = G02WeeklyRotationMatrixStrategy()
