"""Shared matrix-native runner for AlphaGPT A-share RPN formulas."""

from __future__ import annotations

from datetime import date

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    _matrix_ema,
    _matrix_relative,
    _matrix_rolling_corr,
    make_signal_matrix,
    valid_rolling_mean,
)

DEFAULT_PARAMS = [
    {"id": "n_buy", "label": "买入前N名", "type": "int", "default": 30, "min": 5, "max": 200, "step": 1},
    {"id": "n_hold", "label": "持有缓冲前N名", "type": "int", "default": 45, "min": 5, "max": 300, "step": 1},
    {"id": "min_listed_days", "label": "上市观察交易日", "type": "int", "default": 60, "min": 20, "max": 250, "step": 1},
    {"id": "amount_window", "label": "成交额均线窗口", "type": "int", "default": 20, "min": 5, "max": 120, "step": 1},
    {"id": "min_avg_amount", "label": "最低平均成交额", "type": "float", "default": 30000000.0, "min": 0.0, "max": 1000000000.0, "step": 1000000.0},
]


def build_meta(strategy_id: str, name: str, description: str, tags: list[str]) -> dict:
    return {
        "id": strategy_id,
        "name": name,
        "description": description,
        "tags": tags,
        "asset_types": ["stock"],
        "timeframes": ["1d"],
        "basic_filter": {"enabled": False},
        "params": DEFAULT_PARAMS,
        "scoring": {},
        "order_by": "score",
        "descending": True,
        "limit": 45,
        "rebalance": {"mode": "equal_weight"},
        "stop_loss": None,
        "max_hold_days": None,
        "research_only": False,
    }


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
            current_day = date.fromisoformat(labels[0][:10])
            out[0] = current_day.weekday() >= 3
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


def _rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for time_id in range(values.shape[0]):
        start = max(0, time_id - window + 1)
        out[time_id] = np.nansum(values[start : time_id + 1], axis=0)
    return out


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for time_id in range(values.shape[0]):
        start = max(0, time_id - window + 1)
        out[time_id] = np.nanstd(values[start : time_id + 1], axis=0)
    return out


def _rolling_max(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for time_id in range(values.shape[0]):
        start = max(0, time_id - window + 1)
        out[time_id] = np.nanmax(values[start : time_id + 1], axis=0)
    return out


def _rolling_min(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for time_id in range(values.shape[0]):
        start = max(0, time_id - window + 1)
        out[time_id] = np.nanmin(values[start : time_id + 1], axis=0)
    return out


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for time_id in range(values.shape[0]):
        start = max(0, time_id - window + 1)
        out[time_id] = np.nanmean(values[start : time_id + 1], axis=0)
    return out


def _ema_feature(values: np.ndarray, window: int) -> np.ndarray:
    valid = np.isfinite(values)
    filled = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    return _matrix_ema(filled, valid, window).astype(np.float32)


def _max3(values: np.ndarray) -> np.ndarray:
    return np.maximum(values, np.maximum(_delay1(values), _delay2(values))).astype(np.float32)


def _decay(values: np.ndarray) -> np.ndarray:
    return (values + np.float32(0.8) * _delay1(values) + np.float32(0.6) * _delay2(values)).astype(np.float32)


def _gate(condition: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.where(condition > 0, x, y).astype(np.float32)


def _ts_jump(values: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.nanmean(values, axis=0, keepdims=True)
        std = np.nanstd(values, axis=0, keepdims=True) + 1e-6
        z = (values - mean) / std
    return np.nan_to_num(np.maximum(z - 3.0, 0.0), nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


def _cs_robust_norm(values: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        median = np.nanmedian(values, axis=1, keepdims=True)
        mad = np.nanmedian(np.abs(values - median), axis=1, keepdims=True) + 1e-6
        norm = (values - median) / mad
    return np.nan_to_num(np.clip(norm, -5.0, 5.0), nan=0.0, posinf=5.0, neginf=-5.0).astype(np.float32)


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return numerator / (denominator + 1e-9)


def _field_or_zeros(market: MarketDataMatrix, name: str) -> np.ndarray:
    try:
        field = market.field(name)
    except Exception:
        return np.zeros(market.shape, dtype=np.float32)
    return np.nan_to_num(field, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


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
    for time_id in range(eligible.shape[0]):
        asset_ids = np.flatnonzero(eligible[time_id] & np.isfinite(value[time_id]))
        if asset_ids.size == 0:
            continue
        selected = asset_ids[np.argsort(-value[time_id, asset_ids], kind="stable")[:top_n]]
        result[time_id, selected] = True
    return result


def _feature_map(market: MarketDataMatrix, params: dict) -> tuple[dict[str, np.ndarray], np.ndarray]:
    amount_window = _int_param(params, "amount_window", 20, 1)
    min_listed = _int_param(params, "min_listed_days", 60, 1)
    min_avg_amount = _float_param(params, "min_avg_amount", 30_000_000.0, 0.0)

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
    listed_days = np.cumsum(valid, axis=0)

    prev_close = _delay1(market.close)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret_raw = np.log(market.close / (prev_close + 1e-9))
    ret_raw[0, :] = 0.0
    ret1 = _cs_robust_norm(ret_raw)

    turnover = _field_or_zeros(market, "turnover_rate")
    ma5 = valid_rolling_mean(market.close, valid, 5)
    ma20 = valid_rolling_mean(market.close, valid, 20)
    vol_mean5 = valid_rolling_mean(market.volume, valid, 5)
    vol_mean20 = valid_rolling_mean(market.volume, valid, 20)
    vol_ratio5 = _safe_ratio(market.volume, vol_mean5) - 1.0
    vol20 = _rolling_std(ret_raw, 20)
    trend = _safe_ratio(ma5, ma20) - 1.0
    low9 = -_rolling_max(-market.low, 9)
    high9 = _rolling_max(market.high, 9)
    rsv = 100.0 * _safe_ratio(market.close - low9, high9 - low9)
    wr_diff = (rsv - 50.0) / 50.0
    ret5 = _safe_ratio(market.close, np.vstack([np.full((5, market.shape[1]), np.nan, dtype=np.float32), market.close[:-5]])) - 1.0
    ret20 = _safe_ratio(market.close, np.vstack([np.full((20, market.shape[1]), np.nan, dtype=np.float32), market.close[:-20]])) - 1.0
    roc = _safe_ratio(market.close - np.vstack([np.full((12, market.shape[1]), np.nan, dtype=np.float32), market.close[:-12]]), np.vstack([np.full((12, market.shape[1]), np.nan, dtype=np.float32), market.close[:-12]]))
    v_ret = ret_raw * vol_ratio5
    typical_price = (market.high + market.low + market.close) / 3.0
    raw_money = typical_price * market.volume
    tp_delta = typical_price - _delay1(typical_price)
    pos_money = np.where(tp_delta > 0, raw_money, 0.0).astype(np.float32)
    neg_money = np.where(tp_delta < 0, raw_money, 0.0).astype(np.float32)
    money_ratio = _safe_ratio(_rolling_sum(pos_money, 14), _rolling_sum(neg_money, 14))
    mfi = 100.0 - 100.0 / (1.0 + money_ratio)
    amount_sum20 = _rolling_sum(amount, 20)
    volume_sum20 = _rolling_sum(market.volume, 20)
    vwap20 = _safe_ratio(amount_sum20, volume_sum20)
    vwap_dev = _safe_ratio(market.close, vwap20) - 1.0
    vol_ret_corr = _matrix_rolling_corr(ret_raw, market.volume, valid, 20)
    ma20_bias = _safe_ratio(market.close, ma20) - 1.0
    amp1 = _safe_ratio(market.high - market.low, market.close)
    amp20 = valid_rolling_mean(amp1, valid, 20)
    prev_close_raw = _delay1(market.close)
    true_range = np.maximum(
        market.high - market.low,
        np.maximum(np.abs(market.high - prev_close_raw), np.abs(market.low - prev_close_raw)),
    )
    atr14 = valid_rolling_mean(true_range, valid, 14)
    std20_close = _rolling_std(market.close, 20)
    boll_upper = ma20 + 2.0 * std20_close
    boll_lower = ma20 - 2.0 * std20_close
    boll_width20 = _safe_ratio(boll_upper - boll_lower, ma20)
    turnover20 = valid_rolling_mean(turnover, np.isfinite(turnover), 20)
    amount_boost20 = _safe_ratio(amount, avg_amount) - 1.0
    turnover_boost20 = _safe_ratio(turnover, turnover20) - 1.0
    financing_momentum_proxy = 0.5 * amount_boost20 + 0.5 * turnover_boost20
    obv_delta = np.sign(market.close - prev_close_raw) * market.volume
    obv20 = _rolling_sum(obv_delta, 20)
    obv_chg = _safe_ratio(obv20, valid_rolling_mean(np.abs(obv_delta), valid, 20))
    gains14 = valid_rolling_mean(np.maximum(market.close - prev_close_raw, 0.0), valid, 14)
    losses14 = valid_rolling_mean(np.maximum(prev_close_raw - market.close, 0.0), valid, 14)
    rsi14 = 100.0 - 100.0 / (1.0 + _safe_ratio(gains14, losses14))

    corr_ca20 = _matrix_rolling_corr(market.close, amount, valid & amount_valid, 20)
    corr_cv20 = _matrix_rolling_corr(market.close, market.volume, valid, 20)
    corr_cv30 = _matrix_rolling_corr(market.close, market.volume, valid, 30)
    ema60 = _matrix_ema(market.close, valid, 60)
    ma60_bias = _matrix_relative(market.close, ema60)

    features = {
        "RET1": ret1,
        "CA_CORR20_LOW": -_cs_robust_norm(corr_ca20),
        "CV_CORR20_LOW": -_cs_robust_norm(corr_cv20),
        "CV_CORR30_LOW": -_cs_robust_norm(corr_cv30),
        "MA60_BIAS_LOW": -_cs_robust_norm(ma60_bias),
        "AMP20_LOW": -_cs_robust_norm(amp20),
        "WR_DIFF": _cs_robust_norm(wr_diff),
        "RSI14": _cs_robust_norm(rsi14),
        "RSV": _cs_robust_norm(rsv),
        "MFI": _cs_robust_norm(mfi),
        "RET": ret1,
        "RET5": _cs_robust_norm(ret5),
        "RET20": _cs_robust_norm(ret20),
        "ROC": _cs_robust_norm(roc),
        "VOL_CHG": _cs_robust_norm(vol_ratio5),
        "V_RET": _cs_robust_norm(v_ret),
        "VWAP_DEV": _cs_robust_norm(vwap_dev),
        "VOL_RET_CORR": _cs_robust_norm(vol_ret_corr),
        "TREND": _cs_robust_norm(trend),
        "ATR14": _cs_robust_norm(atr14),
        "VOL20": _cs_robust_norm(vol20),
        "BB_WIDTH": _cs_robust_norm(boll_width20),
        "F_BUY_F_REPLAY": _cs_robust_norm(financing_momentum_proxy),
        "OBV_CHG": _cs_robust_norm(obv_chg),
        "BIAS": _cs_robust_norm(ma20_bias),
    }
    eligible = (
        valid
        & amount_valid
        & np.isfinite(avg_amount)
        & np.isfinite(corr_ca20)
        & np.isfinite(corr_cv20)
        & np.isfinite(corr_cv30)
        & np.isfinite(ma60_bias)
        & np.isfinite(amp20)
        & (listed_days >= min_listed)
        & (avg_amount >= min_avg_amount)
    )
    return features, eligible


def evaluate_rpn_formula(tokens: tuple[str, ...], features: dict[str, np.ndarray]) -> np.ndarray:
    stack: list[np.ndarray] = []
    for token in tokens:
        if token in features:
            stack.append(features[token])
        elif token == "ADD":
            y, x = stack.pop(), stack.pop()
            stack.append((x + y).astype(np.float32))
        elif token == "SUB":
            y, x = stack.pop(), stack.pop()
            stack.append((x - y).astype(np.float32))
        elif token == "MUL":
            y, x = stack.pop(), stack.pop()
            stack.append((x * y).astype(np.float32))
        elif token == "DIV":
            y, x = stack.pop(), stack.pop()
            stack.append((x / (y + 1e-6)).astype(np.float32))
        elif token == "NEG":
            stack.append((-stack.pop()).astype(np.float32))
        elif token == "ABS":
            stack.append(np.abs(stack.pop()).astype(np.float32))
        elif token == "SIGN":
            stack.append(np.sign(stack.pop()).astype(np.float32))
        elif token == "GATE":
            y, x, condition = stack.pop(), stack.pop(), stack.pop()
            stack.append(_gate(condition, x, y))
        elif token == "JUMP":
            stack.append(_ts_jump(stack.pop()))
        elif token == "DECAY":
            stack.append(_decay(stack.pop()))
        elif token == "TS_MEAN_10":
            stack.append(_rolling_mean(stack.pop(), 10))
        elif token == "TS_MIN_20":
            stack.append(_rolling_min(stack.pop(), 20))
        elif token == "CS_SCALE":
            stack.append(_cs_robust_norm(stack.pop()))
        elif token == "EMA_20":
            stack.append(_ema_feature(stack.pop(), 20))
        elif token == "DELAY1":
            stack.append(_delay1(stack.pop()))
        elif token == "MAX3":
            stack.append(_max3(stack.pop()))
        else:
            raise ValueError(f"unsupported AlphaGPT token: {token}")
    if len(stack) != 1:
        raise ValueError(f"invalid AlphaGPT formula stack size: {len(stack)}")
    return np.nan_to_num(stack[0], nan=-1e9, posinf=1e9, neginf=-1e9).astype(np.float32)


class AlphaGPTFormulaMatrixStrategy:
    def __init__(self, strategy_id: str, formula_tokens: tuple[str, ...]) -> None:
        self.strategy_id = strategy_id
        self.formula_tokens = formula_tokens

    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "close", "volume", "amount"})

    def required_warmup_bars(self, params: dict) -> int:
        amount_window = _int_param(params, "amount_window", 20, 1)
        min_listed = _int_param(params, "min_listed_days", 60, 1)
        return max(60, 30, amount_window, min_listed) + 5

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        n_buy = _int_param(params, "n_buy", 30, 1)
        n_hold = max(n_buy, _int_param(params, "n_hold", 45, 1))

        features, eligible = _feature_map(market, params)
        value = evaluate_rpn_formula(self.formula_tokens, features)
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
            entry_signal_ids=(f"signal_{self.strategy_id}_top30",),
            exit_signal_ids=(f"signal_{self.strategy_id}_buffer45_exit",),
        )
