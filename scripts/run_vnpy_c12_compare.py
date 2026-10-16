"""Run a vn.py-environment portfolio comparison for AlphaGPT round935 c12.

This script intentionally keeps the TSP strategy formula and A-share execution
rules explicit so the comparison is about backtest engine/accounting behavior,
not formula drift.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import vnpy
    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData
except Exception as exc:  # pragma: no cover - runtime environment check
    raise SystemExit(f"vn.py is not importable in this Python environment: {exc}") from exc


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
KLINE_DIR = DATA_DIR / "kline_daily_enriched"
TSP_BASELINE = ROOT / "tmp_round935_c12_tsp_rerun.json"

FORMULA_TOKENS = (
    "CV_CORR30_LOW",
    "MAX3",
    "MA60_BIAS_LOW",
    "CA_CORR20_LOW",
    "MA60_BIAS_LOW",
    "JUMP",
    "NEG",
    "GATE",
    "CV_CORR30_LOW",
    "DELAY1",
    "GATE",
    "JUMP",
)


@dataclass
class Trade:
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl_pct: float
    pnl_amount: float
    duration: int
    reason: str


def _date_dirs(start: date, end: date) -> list[Path]:
    paths: list[Path] = []
    for path in KLINE_DIR.glob("date=*/part.parquet"):
        text = path.parent.name.removeprefix("date=")
        try:
            day = date.fromisoformat(text)
        except ValueError:
            continue
        if start <= day <= end:
            paths.append(path)
    return sorted(paths, key=lambda p: p.parent.name)


def _load_panel(start: date, end: date, warmup_days: int) -> pd.DataFrame:
    load_start = start - timedelta(days=warmup_days)
    cols = [
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover_rate",
        "consecutive_limit_ups",
        "consecutive_limit_downs",
    ]
    frames: list[pd.DataFrame] = []
    for path in _date_dirs(load_start, end):
        frame = pd.read_parquet(path)
        for col in cols:
            if col not in frame.columns:
                frame[col] = np.nan
        frames.append(frame[cols])
    if not frames:
        raise RuntimeError(f"no parquet files found between {load_start} and {end}")
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"]).dt.date
    panel = panel.drop_duplicates(["date", "symbol"]).sort_values(["date", "symbol"])
    return panel


def _pivot(panel: pd.DataFrame, field: str, dates: list[date], symbols: list[str]) -> np.ndarray:
    table = panel.pivot(index="date", columns="symbol", values=field).reindex(index=dates, columns=symbols)
    return table.to_numpy(dtype=np.float32)


def _delay(values: np.ndarray, bars: int = 1) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    if bars < values.shape[0]:
        out[bars:] = values[:-bars]
    return out


def _delay_zero(values: np.ndarray, bars: int = 1) -> np.ndarray:
    out = np.zeros(values.shape, dtype=np.float32)
    if bars < values.shape[0]:
        out[bars:] = values[:-bars]
    return out


def _rolling_mean(values: np.ndarray, valid: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for i in range(values.shape[0]):
        start = max(0, i - window + 1)
        masked = np.where(valid[start : i + 1], values[start : i + 1], np.nan)
        out[i] = np.nanmean(masked, axis=0)
    return out


def _rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for i in range(values.shape[0]):
        start = max(0, i - window + 1)
        out[i] = np.nansum(values[start : i + 1], axis=0)
    return out


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for i in range(values.shape[0]):
        start = max(0, i - window + 1)
        out[i] = np.nanstd(values[start : i + 1], axis=0)
    return out


def _rolling_max(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for i in range(values.shape[0]):
        start = max(0, i - window + 1)
        out[i] = np.nanmax(values[start : i + 1], axis=0)
    return out


def _rolling_corr(left: np.ndarray, right: np.ndarray, valid: np.ndarray, window: int) -> np.ndarray:
    both = valid & np.isfinite(left) & np.isfinite(right)
    mean_l = _rolling_mean(left, both, window)
    mean_r = _rolling_mean(right, both, window)
    mean_lr = _rolling_mean((left * right).astype(np.float32), both, window)
    mean_l2 = _rolling_mean(np.square(left, dtype=np.float32), both, window)
    mean_r2 = _rolling_mean(np.square(right, dtype=np.float32), both, window)
    cov = mean_lr - mean_l * mean_r
    var_l = mean_l2 - np.square(mean_l, dtype=np.float32)
    var_r = mean_r2 - np.square(mean_r, dtype=np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = cov / np.sqrt(var_l * var_r)
    out[(var_l <= 0) | (var_r <= 0)] = np.nan
    return out.astype(np.float32)


def _ema(values: np.ndarray, valid: np.ndarray, period: int) -> np.ndarray:
    alpha = np.float32(2.0 / (period + 1.0))
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for col in range(values.shape[1]):
        prev = np.nan
        for row in range(values.shape[0]):
            if not valid[row, col] or not np.isfinite(values[row, col]):
                out[row, col] = prev
                continue
            prev = values[row, col] if not np.isfinite(prev) else alpha * values[row, col] + (1 - alpha) * prev
            out[row, col] = prev
    return out


def _cs_robust_norm(values: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        median = np.nanmedian(values, axis=1, keepdims=True)
        mad = np.nanmedian(np.abs(values - median), axis=1, keepdims=True) + 1e-6
        out = (values - median) / mad
    return np.nan_to_num(np.clip(out, -5.0, 5.0), nan=0.0, posinf=5.0, neginf=-5.0).astype(np.float32)


def _safe_ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return (num / (den + 1e-9)).astype(np.float32)


def _max3(values: np.ndarray) -> np.ndarray:
    return np.maximum(values, np.maximum(_delay_zero(values, 1), _delay_zero(values, 2))).astype(np.float32)


def _jump(values: np.ndarray) -> np.ndarray:
    mean = np.nanmean(values, axis=0, keepdims=True)
    std = np.nanstd(values, axis=0, keepdims=True) + 1e-6
    return np.nan_to_num(np.maximum((values - mean) / std - 3.0, 0.0), nan=0.0).astype(np.float32)


def _gate(condition: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.where(condition > 0, x, y).astype(np.float32)


def _eval_formula(tokens: tuple[str, ...], features: dict[str, np.ndarray]) -> np.ndarray:
    stack: list[np.ndarray] = []
    for token in tokens:
        if token in features:
            stack.append(features[token])
        elif token == "NEG":
            stack.append((-stack.pop()).astype(np.float32))
        elif token == "GATE":
            y, x, condition = stack.pop(), stack.pop(), stack.pop()
            stack.append(_gate(condition, x, y))
        elif token == "JUMP":
            stack.append(_jump(stack.pop()))
        elif token == "DELAY1":
            stack.append(_delay_zero(stack.pop(), 1))
        elif token == "MAX3":
            stack.append(_max3(stack.pop()))
        else:
            raise ValueError(f"unsupported token in c12 formula: {token}")
    if len(stack) != 1:
        raise ValueError(f"invalid formula stack size: {len(stack)}")
    return np.nan_to_num(stack[0], nan=-1e9, posinf=1e9, neginf=-1e9).astype(np.float32)


def _weekly_signal_mask(dates: list[date]) -> np.ndarray:
    out = np.zeros(len(dates), dtype=bool)
    for i in range(len(dates) - 1):
        if dates[i + 1].isocalendar()[:2] != dates[i].isocalendar()[:2]:
            out[i] = True
    if dates:
        out[-1] = out[-1] or dates[-1].weekday() >= 3
    return out


def _top_mask(eligible: np.ndarray, value: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros(eligible.shape, dtype=bool)
    for i in range(value.shape[0]):
        ids = np.flatnonzero(eligible[i] & np.isfinite(value[i]))
        if ids.size:
            chosen = ids[np.argsort(-value[i, ids], kind="stable")[:n]]
            out[i, chosen] = True
    return out


def _score_rank(eligible: np.ndarray, value: np.ndarray) -> np.ndarray:
    score = np.zeros(value.shape, dtype=np.float32)
    for i in range(value.shape[0]):
        ids = np.flatnonzero(eligible[i] & np.isfinite(value[i]))
        if ids.size == 1:
            score[i, ids[0]] = 100.0
        elif ids.size > 1:
            order = ids[np.argsort(-value[i, ids], kind="stable")]
            ranks = np.arange(ids.size, dtype=np.float32)
            score[i, order] = (1 - ranks / np.float32(ids.size - 1)) * 100.0
    return score


def _signals(panel: pd.DataFrame, dates: list[date], symbols: list[str]) -> dict[str, np.ndarray]:
    open_ = _pivot(panel, "open", dates, symbols)
    high = _pivot(panel, "high", dates, symbols)
    low = _pivot(panel, "low", dates, symbols)
    close = _pivot(panel, "close", dates, symbols)
    volume = _pivot(panel, "volume", dates, symbols)
    amount = _pivot(panel, "amount", dates, symbols)

    valid = np.isfinite(close) & np.isfinite(open_) & (close > 0) & (open_ > 0) & np.isfinite(volume) & (volume > 0)
    amount_valid = np.isfinite(amount) & (amount > 0)
    avg_amount = _rolling_mean(amount, valid & amount_valid, 20)
    listed_days = np.cumsum(valid, axis=0)
    prev_close = _delay(close, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret_raw = np.log(close / (prev_close + 1e-9))
    ret_raw[0] = 0
    corr_ca20 = _rolling_corr(close, amount, valid & amount_valid, 20)
    corr_cv30 = _rolling_corr(close, volume, valid, 30)
    ema60 = _ema(close, valid, 60)
    ma60_bias = _safe_ratio(close, ema60) - 1.0
    features = {
        "CA_CORR20_LOW": -_cs_robust_norm(corr_ca20),
        "CV_CORR30_LOW": -_cs_robust_norm(corr_cv30),
        "MA60_BIAS_LOW": -_cs_robust_norm(ma60_bias),
    }
    eligible = (
        valid
        & amount_valid
        & np.isfinite(avg_amount)
        & np.isfinite(corr_ca20)
        & np.isfinite(corr_cv30)
        & np.isfinite(ma60_bias)
        & (listed_days >= 60)
        & (avg_amount >= 30_000_000.0)
    )
    value = _eval_formula(FORMULA_TOKENS, features)
    signal_days = _weekly_signal_mask(dates)
    buy_pool = _top_mask(eligible, value, 30)
    buffer_pool = _top_mask(eligible, value, 45)
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "entry": buy_pool & signal_days[:, None],
        "exit": (~buffer_pool) & signal_days[:, None],
        "score": _score_rank(eligible, value),
    }


def _vnpy_bar_sample(panel: pd.DataFrame) -> BarData:
    row = panel.iloc[0]
    symbol = str(row["symbol"])
    exchange = Exchange.SSE if symbol.endswith(".SH") else Exchange.SZSE
    return BarData(
        symbol=symbol.split(".")[0],
        exchange=exchange,
        datetime=pd.Timestamp(row["date"]).to_pydatetime(),
        interval=Interval.DAILY,
        volume=float(row["volume"] or 0),
        turnover=float(row["amount"] or 0),
        open_price=float(row["open"] or 0),
        high_price=float(row["high"] or 0),
        low_price=float(row["low"] or 0),
        close_price=float(row["close"] or 0),
        gateway_name="TSP_PARQUET",
    )


def _run_portfolio(
    dates: list[date],
    symbols: list[str],
    sig: dict[str, np.ndarray],
    start: date,
    end: date,
) -> dict:
    start_idx = next(i for i, day in enumerate(dates) if day >= start)
    end_idx = max(i for i, day in enumerate(dates) if day <= end)
    initial = 1_000_000.0
    cash = initial
    positions: dict[int, dict] = {}
    trades: list[Trade] = []
    equity_curve: list[dict] = []
    buy_cost = 0.0003 + 10 / 10000
    sell_cost = 0.0003 + 0.001 + 10 / 10000
    max_positions = 5
    max_exposure_pct = 0.5
    stop_loss = 0.10
    trailing_stop = 0.12
    open_ = sig["open"]
    high = sig["high"]
    low = sig["low"]
    close = sig["close"]
    ent_raw = sig["entry"]
    ext_raw = sig["exit"]
    score = sig["score"]

    def valid_price(x: float) -> bool:
        return bool(np.isfinite(x) and x > 0)

    def market_value(day_idx: int) -> float:
        value = 0.0
        for asset_id, pos in positions.items():
            mark = close[day_idx, asset_id]
            if not valid_price(mark):
                mark = pos["entry_price"]
            value += pos["shares"] * float(mark)
        return value

    def sell(asset_id: int, day_idx: int, price: float, reason: str) -> None:
        nonlocal cash
        pos = positions.pop(asset_id)
        exit_value = pos["shares"] * price * (1 - sell_cost)
        cash += exit_value
        pnl_amount = exit_value - pos["entry_value"]
        trades.append(
            Trade(
                symbol=symbols[asset_id],
                entry_date=dates[pos["entry_idx"]].isoformat(),
                exit_date=dates[day_idx].isoformat(),
                entry_price=round(float(pos["entry_price"]), 4),
                exit_price=round(float(price), 4),
                shares=int(pos["shares"]),
                pnl_pct=round(float(pnl_amount / pos["entry_value"]), 6),
                pnl_amount=round(float(pnl_amount), 2),
                duration=int(pos["hold_days"]),
                reason=reason,
            )
        )

    for day_idx in range(start_idx, end_idx + 1):
        day = dates[day_idx]
        sold_today: set[int] = set()
        for pos in positions.values():
            pos["hold_days"] += 1

        for asset_id in list(positions):
            pos = positions.get(asset_id)
            if pos is None or pos["entry_idx"] == day_idx:
                continue
            risk_lines = [
                (pos["entry_price"] * (1 - stop_loss), "stop_loss"),
                (pos["max_high"] * (1 - trailing_stop), "trailing_stop"),
            ]
            stop_price, reason = max(risk_lines, key=lambda item: item[0])
            price = None
            if valid_price(open_[day_idx, asset_id]) and open_[day_idx, asset_id] <= stop_price:
                price = float(open_[day_idx, asset_id])
            elif valid_price(low[day_idx, asset_id]) and low[day_idx, asset_id] <= stop_price:
                price = float(stop_price)
            if price is not None:
                sell(asset_id, day_idx, price, reason)
                sold_today.add(asset_id)

        for asset_id in list(positions):
            if day_idx == end_idx:
                price = open_[day_idx, asset_id]
                if valid_price(price):
                    sell(asset_id, day_idx, float(price), "end")
                    sold_today.add(asset_id)
                continue
            if day_idx > 0 and ext_raw[day_idx - 1, asset_id] and valid_price(open_[day_idx, asset_id]):
                sell(asset_id, day_idx, float(open_[day_idx, asset_id]), "signal")
                sold_today.add(asset_id)

        if day_idx < end_idx and day_idx > 0:
            candidates = np.flatnonzero(ent_raw[day_idx - 1] & np.isfinite(open_[day_idx]))
            candidates = [i for i in candidates if i not in positions and i not in sold_today and valid_price(open_[day_idx, i])]
            candidates.sort(key=lambda i: float(score[day_idx - 1, i]), reverse=True)
            slots = max_positions - len(positions)
            if slots > 0 and candidates:
                selected = candidates[:slots]
                equity_before = cash + market_value(day_idx)
                current_mv = market_value(day_idx)
                capacity = equity_before * max_exposure_pct - current_mv
                target_value = equity_before * max_exposure_pct / max_positions
                total_budget = min(cash, capacity, target_value * len(selected))
                for asset_id in selected:
                    if len(positions) >= max_positions:
                        break
                    price = float(open_[day_idx, asset_id])
                    allocation = min(total_budget / len(selected), target_value, cash)
                    shares = int(np.floor(allocation / (price * (1 + buy_cost)) / 100) * 100)
                    entry_value = shares * price * (1 + buy_cost)
                    if shares <= 0 or entry_value > cash:
                        continue
                    cash -= entry_value
                    positions[asset_id] = {
                        "entry_idx": day_idx,
                        "entry_price": price,
                        "entry_value": entry_value,
                        "shares": shares,
                        "hold_days": 0,
                        "max_high": price,
                    }

        for asset_id, pos in positions.items():
            if valid_price(high[day_idx, asset_id]):
                pos["max_high"] = max(pos["max_high"], float(high[day_idx, asset_id]))

        equity = cash + market_value(day_idx)
        equity_curve.append(
            {
                "date": day.isoformat(),
                "value": round(float(equity), 2),
                "cash": round(float(cash), 2),
                "positions": len(positions),
                "exposure": round(float(market_value(day_idx) / equity), 4) if equity > 0 else 0.0,
            }
        )

    return {"stats": _stats(equity_curve, trades, initial), "equity_curve": equity_curve, "trades": [asdict(t) for t in trades]}


def _stats(equity_curve: list[dict], trades: list[Trade], initial: float) -> dict:
    values = np.array([row["value"] for row in equity_curve], dtype=float)
    exposures = np.array([row["exposure"] for row in equity_curve], dtype=float)
    total_return = values[-1] / initial - 1
    daily = values[1:] / values[:-1] - 1
    peaks = np.maximum.accumulate(values)
    dd = values / peaks - 1
    pnls = np.array([trade.pnl_pct for trade in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    avg_win = float(np.mean(wins)) if len(wins) else 0.0
    avg_loss = abs(float(np.mean(losses))) if len(losses) else 0.0
    sortino_down = np.minimum(daily, 0)
    return {
        "total_return": round(float(total_return), 4),
        "annual_return": round(float((1 + total_return) ** (252 / max(len(values), 1)) - 1), 4),
        "max_drawdown": round(float(dd.min()), 4),
        "sharpe": round(float(np.mean(daily) / np.std(daily) * np.sqrt(252)), 2) if len(daily) and np.std(daily) > 0 else 0.0,
        "sortino": round(float(np.mean(daily) / np.sqrt(np.mean(sortino_down ** 2)) * np.sqrt(252)), 2)
        if len(daily) and np.sqrt(np.mean(sortino_down ** 2)) > 0
        else None,
        "win_rate": round(float(len(wins) / len(pnls)), 4) if len(pnls) else 0.0,
        "profit_factor": round(float(avg_win / avg_loss), 2) if avg_loss > 0 else None,
        "n_trades": int(len(trades)),
        "final_equity": round(float(values[-1]), 2),
        "avg_exposure": round(float(np.mean(exposures)), 4) if len(exposures) else 0.0,
        "max_exposure": round(float(np.max(exposures)), 4) if len(exposures) else 0.0,
    }


def _load_tsp_reference() -> dict | None:
    if not TSP_BASELINE.exists():
        return None
    rows = json.loads(TSP_BASELINE.read_text())
    for row in rows:
        if row.get("grid") == "stop10_trail12_exp50_pos5":
            return {key: row.get(key) for key in ("total_return", "annual_return", "max_drawdown", "sharpe", "run_id", "n_trades")}
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 9, 30))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--warmup-days", type=int, default=150)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp_vnpy_round935_c12_compare.json")
    args = parser.parse_args()

    panel = _load_panel(args.start, args.end, args.warmup_days)
    bar_sample = _vnpy_bar_sample(panel)
    dates = sorted(panel["date"].unique().tolist())
    symbols = sorted(panel["symbol"].unique().tolist())
    sig = _signals(panel, dates, symbols)
    result = _run_portfolio(dates, symbols, sig, args.start, args.end)
    output = {
        "environment": {
            "python": "vnpy310",
            "vnpy_version": getattr(vnpy, "__version__", "unknown"),
            "vnpy_bar_sample": {
                "symbol": bar_sample.symbol,
                "exchange": bar_sample.exchange.value,
                "interval": bar_sample.interval.value,
                "gateway_name": bar_sample.gateway_name,
            },
        },
        "strategy_id": "ai_alphagpt_round935_c12_jump_delay",
        "grid": "stop10_trail12_exp50_pos5",
        "period": {"start": args.start.isoformat(), "end": args.end.isoformat(), "warmup_days": args.warmup_days},
        "vnpy_adapter": result,
        "tsp_reference": _load_tsp_reference(),
    }
    ref = output["tsp_reference"]
    if ref:
        output["diff_vs_tsp"] = {
            key: round(float(result["stats"].get(key, 0.0)) - float(ref.get(key, 0.0)), 6)
            for key in ("total_return", "annual_return", "max_drawdown", "sharpe")
        }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("environment", "strategy_id", "grid", "period", "tsp_reference", "diff_vs_tsp") if k in output}, ensure_ascii=False, indent=2))
    print(f"saved to {args.output}")


if __name__ == "__main__":
    main()
