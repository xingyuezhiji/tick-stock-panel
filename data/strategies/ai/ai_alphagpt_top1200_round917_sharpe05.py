"""AlphaGPT round 917 Top1200 weekly rotation with Sharpe-weighted reward."""

from __future__ import annotations

from datetime import date

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    valid_rolling_mean,
)

META: dict = {
    "id": "ai_alphagpt_top1200_round917_sharpe05",
    "name": "AlphaGPT Top1200 Round917 Sharpe05",
    "description": "AlphaGPT round 917候选, Sharpe reward权重0.5, 每周Top30买入, Top45持有缓冲",
    "tags": ["AlphaGPT", "Top1200", "CA_CORR20_LOW", "Sharpe05"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "basic_filter": {"enabled": False},
    "params": [
        {"id": "n_buy", "label": "买入前N名", "type": "int", "default": 30, "min": 5, "max": 200, "step": 1},
        {"id": "n_hold", "label": "持有缓冲前N名", "type": "int", "default": 45, "min": 5, "max": 300, "step": 1},
        {"id": "universe_size", "label": "流动性股票池", "type": "int", "default": 1200, "min": 100, "max": 5000, "step": 100},
        {"id": "min_listed_days", "label": "上市观察交易日", "type": "int", "default": 60, "min": 20, "max": 250, "step": 1},
        {"id": "amount_window", "label": "成交额均线窗口", "type": "int", "default": 20, "min": 5, "max": 120, "step": 1},
        {"id": "min_avg_amount", "label": "最低平均成交额", "type": "float", "default": 30000000.0, "min": 0.0, "max": 1000000000.0, "step": 1000000.0},
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
ENTRY_SIGNALS = ["signal_alphagpt_top1200_round917_sharpe05_top30"]
EXIT_SIGNALS = ["signal_alphagpt_top1200_round917_sharpe05_buffer45_exit"]
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


def _weekly_signal_mask(labels: tuple[str, ...]) -> np.ndarray:
    out = np.zeros(len(labels), dtype=bool)
    if len(labels) < 2:
        if labels:
            out[0] = date.fromisoformat(labels[0][:10]).weekday() >= 3
        return out
    days = [date.fromisoformat(label[:10]) for label in labels]
    weeks = [day.isocalendar()[:2] for day in days]
    for time_id in range(len(labels) - 1):
        if weeks[time_id + 1] != weeks[time_id]:
            out[time_id] = True
    out[-1] = out[-1] or days[-1].weekday() >= 3
    return out


def _delay1(values: np.ndarray) -> np.ndarray:
    out = np.zeros(values.shape, dtype=np.float32)
    out[1:] = values[:-1]
    return out


def _delay2(values: np.ndarray) -> np.ndarray:
    out = np.zeros(values.shape, dtype=np.float32)
    out[2:] = values[:-2]
    return out


def _max3(values: np.ndarray) -> np.ndarray:
    return np.maximum(values, np.maximum(_delay1(values), _delay2(values))).astype(np.float32)


def _decay(values: np.ndarray) -> np.ndarray:
    return (values + np.float32(0.8) * _delay1(values) + np.float32(0.6) * _delay2(values)).astype(np.float32)


def _cs_robust_norm(values: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        median = np.nanmedian(values, axis=1, keepdims=True)
        mad = np.nanmedian(np.abs(values - median), axis=1, keepdims=True) + 1e-6
        norm = (values - median) / mad
    return np.nan_to_num(np.clip(norm, -5.0, 5.0), nan=0.0, posinf=5.0, neginf=-5.0).astype(np.float32)


def _score_rank(eligible: np.ndarray, value: np.ndarray) -> np.ndarray:
    score = np.zeros(value.shape, dtype=np.float32)
    for time_id in range(value.shape[0]):
        asset_ids = np.flatnonzero(eligible[time_id] & np.isfinite(value[time_id]))
        count = asset_ids.size
        if count == 0:
            continue
        order = asset_ids[np.argsort(-value[time_id, asset_ids], kind="stable")]
        if count == 1:
            score[time_id, order[0]] = np.float32(100.0)
            continue
        ranks = np.arange(count, dtype=np.float32)
        score[time_id, order] = (np.float32(1.0) - ranks / np.float32(count - 1)) * np.float32(100.0)
    return score


def _top_rank_mask(eligible: np.ndarray, value: np.ndarray, top_n: int) -> np.ndarray:
    result = np.zeros(eligible.shape, dtype=bool)
    for time_id in range(value.shape[0]):
        asset_ids = np.flatnonzero(eligible[time_id] & np.isfinite(value[time_id]))
        if asset_ids.size == 0:
            continue
        selected = asset_ids[np.argsort(-value[time_id, asset_ids], kind="stable")[:top_n]]
        result[time_id, selected] = True
    return result


def _ashare_universe_mask(symbols: tuple[str, ...]) -> np.ndarray:
    keep = []
    for symbol in symbols:
        code = str(symbol)
        keep.append(
            code.endswith((".SH", ".SZ"))
            and not code.endswith(".BJ")
            and not code.startswith(("4", "8", "92"))
        )
    return np.asarray(keep, dtype=bool)


def _rolling_corr(left: np.ndarray, right: np.ndarray, valid: np.ndarray, window: int) -> np.ndarray:
    both_valid = valid & np.isfinite(left) & np.isfinite(right)
    left_mean = valid_rolling_mean(left, both_valid, window)
    right_mean = valid_rolling_mean(right, both_valid, window)
    cross_mean = valid_rolling_mean(left * right, both_valid, window)
    left_sq_mean = valid_rolling_mean(left * left, both_valid, window)
    right_sq_mean = valid_rolling_mean(right * right, both_valid, window)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = cross_mean - left_mean * right_mean
        left_var = left_sq_mean - left_mean * left_mean
        right_var = right_sq_mean - right_mean * right_mean
        corr = cov / (np.sqrt(np.maximum(left_var, 1e-9)) * np.sqrt(np.maximum(right_var, 1e-9)))
    return np.clip(corr, -1.0, 1.0).astype(np.float32)


def _ca_corr20_low(market: MarketDataMatrix, valid: np.ndarray) -> np.ndarray:
    corr = _rolling_corr(market.close, market.field("amount"), valid, 20)
    return -_cs_robust_norm(corr)


def compute_alphagpt_score(market: MarketDataMatrix, params: dict) -> tuple[np.ndarray, np.ndarray]:
    amount_window = _int_param(params, "amount_window", 20, 1)
    universe_size = _int_param(params, "universe_size", 1200, 1)
    min_listed = _int_param(params, "min_listed_days", 60, 1)
    min_avg_amount = _float_param(params, "min_avg_amount", 30_000_000.0, 0.0)

    amount = market.field("amount")
    valid = (
        np.isfinite(market.open)
        & np.isfinite(market.high)
        & np.isfinite(market.low)
        & np.isfinite(market.close)
        & (market.open > 0)
        & (market.high > 0)
        & (market.low > 0)
        & (market.close > 0)
        & np.isfinite(market.volume)
        & (market.volume > 0)
        & np.isfinite(amount)
        & (amount > 0)
    )
    valid &= _ashare_universe_mask(market.symbols)[None, :]

    avg_amount = valid_rolling_mean(amount, valid, amount_window)
    listed_days = np.cumsum(valid, axis=0)
    liquid_pool = _top_rank_mask(valid & np.isfinite(avg_amount), avg_amount, universe_size)

    ca_corr20_low = _ca_corr20_low(market, valid)

    # AlphaGPT VM formula:
    # CA_CORR20_LOW DELAY1 MAX3 DELAY1 MAX3 DELAY1 MAX3 NEG MAX3 MAX3 ABS DECAY
    value = ca_corr20_low
    value = _delay1(value)
    value = _max3(value)
    value = _delay1(value)
    value = _max3(value)
    value = _delay1(value)
    value = _max3(value)
    value = -value
    value = _max3(value)
    value = _max3(value)
    value = np.abs(value)
    value = _decay(value)
    value = np.nan_to_num(value, nan=-1e9, posinf=1e9, neginf=-1e9).astype(np.float32)

    eligible = (
        valid
        & np.isfinite(ca_corr20_low)
        & np.isfinite(avg_amount)
        & liquid_pool
        & (listed_days >= min_listed)
        & (avg_amount >= min_avg_amount)
    )
    return value, eligible


class AlphaGPTTop1200Round917Sharpe05MatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume", "amount"})

    def required_warmup_bars(self, params: dict) -> int:
        amount_window = _int_param(params, "amount_window", 20, 1)
        min_listed = _int_param(params, "min_listed_days", 60, 1)
        return max(20, amount_window, min_listed) + 20

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        n_buy = _int_param(params, "n_buy", 30, 1)
        n_hold = max(n_buy, _int_param(params, "n_hold", 45, 1))

        value, eligible = compute_alphagpt_score(market, params)
        score = _score_rank(eligible, value)
        signal_days = _weekly_signal_mask(market.timestamp_labels)
        buy_pool = _top_rank_mask(eligible, value, n_buy)
        buffer_pool = _top_rank_mask(eligible, value, n_hold)

        entry = buy_pool & signal_days[:, None]
        exit_ = (~buffer_pool) & signal_days[:, None]
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_alphagpt_top1200_round917_sharpe05_top30",),
            exit_signal_ids=("signal_alphagpt_top1200_round917_sharpe05_buffer45_exit",),
        )


MATRIX_STRATEGY = AlphaGPTTop1200Round917Sharpe05MatrixStrategy()
