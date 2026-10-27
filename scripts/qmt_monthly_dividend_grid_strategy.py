#encoding:gbk
"""QMT monthly dividend/grid ETF strategy.

Copy this file into QMT's Python strategy editor and run it in backtest mode.

Idea:
- Trade broad A-share ETF proxies: HS300, CSI500, dividend, dividend-low-vol.
- Check signals once per month.
- Keep a target allocation and reinvest idle cash monthly.
- Add one grid tranche when an ETF drops to a lower grid level.
- Trim the extra grid tranche when price rebounds.

- ENABLE_ORDER is True for QMT backtest by default.
- The script prints every generated order. Do not run it in a live account
  before you have checked QMT account/broker settings.
"""

import math
import time


# ===== User parameters =====
ENABLE_ORDER = True
ACCOUNT_ID = "test"
STRATEGY_NAME = "monthly_dividend_grid"

# ETF proxies. Adjust these if your QMT data source uses different symbols.
ETF_CONFIG = [
    # symbol, name, target weight, first usable date in this strategy
    ("510300.SH", "HS300 ETF", 0.18, "20120528"),
    ("510050.SH", "SSE50 ETF", 0.10, "20050223"),
    ("510500.SH", "CSI500 ETF", 0.07, "20130315"),
    ("512100.SH", "CSI1000 ETF", 0.05, "20161104"),
    ("510880.SH", "SSE Dividend ETF", 0.28, "20070118"),
    ("515080.SH", "CSI Dividend ETF", 0.13, "20200101"),
    ("512890.SH", "Dividend LowVol ETF", 0.09, "20200101"),
    ("518880.SH", "Gold ETF", 0.10, "20130729"),
]
BACKTEST_START_DATE = "20170101"

INITIAL_CAPITAL = 1000000.0
CASH_BUFFER_PCT = 0.15
GRID_STEP = 0.04              # every 4% drawdown adds one tranche
GRID_TAKE_PROFIT = 0.04       # 4% rebound trims one tranche
GRID_TRANCHE_PCT = 0.04       # each grid add uses 4% of total equity
MAX_GRID_LEVEL = 3
MA_LOOKBACK = 60
LOW_PRICE_DISCOUNT = 0.04     # only add below MA60 * (1 - 4%)
DRIFT_REBALANCE_PCT = 0.15    # monthly target drift threshold
MIN_ORDER_VALUE = 3000.0
ORDER_CASH_SAFETY = 0.98     # leave room for QMT price/fee rounding


# QMT passorder constants used by many mini-QMT examples.
# If your QMT environment uses a different order convention, update here only.
BUY_OP = 23
SELL_OP = 24
ORDER_BY_SHARES = 1101
PRICE_LATEST = 5
QUICK_TRADE = 2


STATE = {
    "cash": INITIAL_CAPITAL,
    "pos": {},
    "anchor": {},
    "grid_level": {},
    "last_grid_buy": {},
    "last_month": "",
    "last_run_date": "",
}

TRADE_LOG = []


def _log(msg):
    print("[DIV-GRID]", msg)


def _log_trade(date_text, side, symbol, qty, price, reason):
    names = _names()
    side_text = "BUY" if side == "buy" else "SELL"
    amount = float(qty) * float(price)
    row = {
        "date": str(date_text),
        "side": side_text,
        "symbol": symbol,
        "name": names.get(symbol, ""),
        "qty": int(qty),
        "price": float(price),
        "amount": amount,
        "reason": reason,
        "cash": float(STATE["cash"]),
        "pos": int(STATE["pos"].get(symbol, 0)),
    }
    TRADE_LOG.append(row)
    print(
        "[TRADE] date={0} side={1} symbol={2} name={3} qty={4} price={5:.4f} "
        "amount={6:.2f} reason={7} cash={8:.2f} pos={9}".format(
            row["date"],
            row["side"],
            row["symbol"],
            row["name"],
            row["qty"],
            row["price"],
            row["amount"],
            row["reason"],
            row["cash"],
            row["pos"],
        )
    )


def _symbols():
    return [row[0] for row in ETF_CONFIG]


def _weights():
    return dict((row[0], float(row[2])) for row in ETF_CONFIG)


def _names():
    return dict((row[0], row[1]) for row in ETF_CONFIG)


def _start_dates():
    return dict((row[0], str(row[3])) for row in ETF_CONFIG)


def _active_symbols(date_text):
    starts = _start_dates()
    if str(date_text) < BACKTEST_START_DATE:
        return []
    return [symbol for symbol in _symbols() if str(date_text) >= starts.get(symbol, "19000101")]


def _active_weights(date_text):
    active = _active_symbols(date_text)
    base = _weights()
    total = sum(base.get(symbol, 0.0) for symbol in active)
    if total <= 0:
        return {}
    return dict((symbol, base.get(symbol, 0.0) / total) for symbol in active)


def _lot_qty(raw_qty):
    try:
        qty = int(raw_qty)
    except Exception:
        return 0
    return int(qty / 100) * 100


def _safe_float(v, default=None):
    try:
        if v is None:
            return default
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def _bar_date(ContextInfo):
    """Return YYYYMMDD. Handles several QMT runtime variants."""
    try:
        tag = ContextInfo.get_bar_timetag(ContextInfo.barpos)
        try:
            text = ContextInfo.timetag_to_datetime(tag, "%Y%m%d")
        except Exception:
            text = time.strftime("%Y%m%d", time.localtime(float(tag) / 1000.0))
        return str(text)[:8]
    except Exception:
        return time.strftime("%Y%m%d")


def _month_key(date_text):
    return str(date_text)[:6]


def _extract_series(raw, symbol, field):
    """Best-effort parser for QMT get_market_data/get_market_data_ex outputs."""
    if raw is None:
        return []
    obj = raw
    try:
        if isinstance(raw, dict) and symbol in raw:
            obj = raw.get(symbol)
        elif isinstance(raw, dict) and field in raw:
            obj = raw.get(field)
    except Exception:
        obj = raw

    # pandas DataFrame / Series style
    try:
        if hasattr(obj, "__getitem__") and field in getattr(obj, "columns", []):
            vals = list(obj[field].values)
            return [_safe_float(v) for v in vals if _safe_float(v) is not None]
    except Exception:
        pass
    try:
        if hasattr(obj, "values") and not isinstance(obj, dict):
            vals = list(obj.values)
            return [_safe_float(v) for v in vals if _safe_float(v) is not None]
    except Exception:
        pass

    if isinstance(obj, dict):
        val = obj.get(field)
        if isinstance(val, (list, tuple)):
            return [_safe_float(v) for v in val if _safe_float(v) is not None]
        val = _safe_float(val)
        return [] if val is None else [val]
    if isinstance(obj, (list, tuple)):
        return [_safe_float(v) for v in obj if _safe_float(v) is not None]
    val = _safe_float(obj)
    return [] if val is None else [val]


def _get_close_series(ContextInfo, symbol, count, end_date):
    fields = ["close"]
    last_error = None
    # Common QMT APIs differ slightly across versions. Try the usual variants.
    for call_kind in (1, 2, 3):
        try:
            if call_kind == 1:
                raw = ContextInfo.get_market_data_ex(
                    fields,
                    [symbol],
                    period="1d",
                    count=count,
                    end_time=end_date,
                )
            elif call_kind == 2:
                raw = ContextInfo.get_market_data(
                    fields,
                    stock_code=[symbol],
                    period="1d",
                    count=count,
                    end_time=end_date,
                )
            else:
                raw = ContextInfo.get_market_data(
                    fields,
                    [symbol],
                    "1d",
                    "",
                    end_date,
                    count,
                )
            series = _extract_series(raw, symbol, "close")
            if series:
                return series
        except Exception as exc:
            last_error = exc
    _log("cannot read close series for {0}: {1}".format(symbol, last_error))
    return []


def _latest_prices(ContextInfo, end_date):
    out = {}
    for symbol in _active_symbols(end_date):
        series = _get_close_series(ContextInfo, symbol, max(MA_LOOKBACK + 5, 80), end_date)
        if series:
            out[symbol] = {
                "close": series[-1],
                "ma": sum(series[-MA_LOOKBACK:]) / min(len(series), MA_LOOKBACK),
            }
    return out


def _portfolio_value(prices):
    value = float(STATE["cash"])
    for symbol, qty in STATE["pos"].items():
        px = prices.get(symbol, {}).get("close")
        if px is not None:
            value += float(qty) * float(px)
    return value


def _send_order(ContextInfo, symbol, side, qty, price, reason):
    qty = _lot_qty(qty)
    if qty <= 0:
        return False
    if price is None or price <= 0:
        return False
    if qty * price < MIN_ORDER_VALUE:
        return False

    if side == "buy":
        need = qty * price
        if need > STATE["cash"]:
            qty = _lot_qty((STATE["cash"] * ORDER_CASH_SAFETY) / price)
            if qty <= 0:
                return False
            need = qty * price
            if need < MIN_ORDER_VALUE:
                return False
        op = BUY_OP
    else:
        hold = int(STATE["pos"].get(symbol, 0))
        qty = min(qty, hold)
        qty = _lot_qty(qty)
        if qty <= 0:
            return False
        op = SELL_OP

    names = _names()
    _log("{0} {1} {2} qty={3} ref={4:.4f} {5}".format(
        "BUY" if side == "buy" else "SELL",
        symbol,
        names.get(symbol, ""),
        qty,
        price,
        reason,
    ))

    if not ENABLE_ORDER:
        _log("dry-run: ENABLE_ORDER=False, no QMT order sent")
        return False

    try:
        # Global passorder is available inside QMT strategy runtime.
        passorder(op, ORDER_BY_SHARES, ACCOUNT_ID, symbol, PRICE_LATEST, 0, qty, STRATEGY_NAME, QUICK_TRADE, reason, ContextInfo)
    except Exception as exc:
        _log("passorder failed for {0}: {1}".format(symbol, exc))
        return False

    # Update local bookkeeping after passorder returns without exception.
    if side == "buy":
        STATE["cash"] -= qty * price
        STATE["pos"][symbol] = int(STATE["pos"].get(symbol, 0)) + qty
    else:
        STATE["cash"] += qty * price
        STATE["pos"][symbol] = int(STATE["pos"].get(symbol, 0)) - qty
    _log_trade(_bar_date(ContextInfo), side, symbol, qty, price, reason)
    return True


def _initial_or_monthly_rebalance(ContextInfo, prices, total_value, date_text, skip_symbols=None):
    skip_symbols = skip_symbols or set()
    weights = _active_weights(date_text)
    investable = total_value * (1.0 - CASH_BUFFER_PCT)
    for symbol in _active_symbols(date_text):
        if symbol not in prices:
            continue
        if symbol in skip_symbols:
            continue
        price = prices[symbol]["close"]
        target_value = investable * weights.get(symbol, 0.0)
        current_value = int(STATE["pos"].get(symbol, 0)) * price
        diff = target_value - current_value
        drift = abs(diff) / total_value if total_value > 0 else 0.0
        if current_value <= 0:
            qty = _lot_qty(target_value / price)
            _send_order(ContextInfo, symbol, "buy", qty, price, "monthly build/reinvest cash")
        elif diff > MIN_ORDER_VALUE and drift >= DRIFT_REBALANCE_PCT:
            qty = _lot_qty(diff / price)
            _send_order(ContextInfo, symbol, "buy", qty, price, "monthly rebalance buy/reinvest")
        elif diff < -MIN_ORDER_VALUE and drift >= DRIFT_REBALANCE_PCT:
            qty = _lot_qty((-diff) / price)
            _send_order(ContextInfo, symbol, "sell", qty, price, "monthly rebalance trim")


def _grid_actions(ContextInfo, prices, total_value):
    traded_symbols = set()
    for symbol in prices.keys():
        if symbol not in prices:
            continue
        price = prices[symbol]["close"]
        ma = prices[symbol]["ma"]
        anchor = STATE["anchor"].get(symbol)
        if anchor is None or anchor <= 0:
            STATE["anchor"][symbol] = price
            STATE["grid_level"][symbol] = 0
            STATE["last_grid_buy"][symbol] = price
            continue

        level = int(STATE["grid_level"].get(symbol, 0))
        next_buy_price = anchor * (1.0 - GRID_STEP * (level + 1))
        is_low = price <= ma * (1.0 - LOW_PRICE_DISCOUNT)
        if level < MAX_GRID_LEVEL and price <= next_buy_price and is_low:
            value = total_value * GRID_TRANCHE_PCT
            qty = _lot_qty(value / price)
            ok = _send_order(ContextInfo, symbol, "buy", qty, price, "low grid add L{0}".format(level + 1))
            if ok:
                STATE["grid_level"][symbol] = level + 1
                STATE["last_grid_buy"][symbol] = price
                traded_symbols.add(symbol)
            continue

        last_buy = STATE["last_grid_buy"].get(symbol, anchor)
        if level > 0 and price >= last_buy * (1.0 + GRID_TAKE_PROFIT):
            value = total_value * GRID_TRANCHE_PCT
            qty = _lot_qty(value / price)
            ok = _send_order(ContextInfo, symbol, "sell", qty, price, "grid rebound trim L{0}".format(level))
            if ok:
                STATE["grid_level"][symbol] = max(0, level - 1)
                if STATE["grid_level"][symbol] == 0:
                    STATE["last_grid_buy"][symbol] = STATE["anchor"].get(symbol, price)
                traded_symbols.add(symbol)
            continue
    return traded_symbols


def _run_monthly(ContextInfo):
    date_text = _bar_date(ContextInfo)
    if date_text < BACKTEST_START_DATE:
        return
    if date_text == STATE["last_run_date"]:
        return
    STATE["last_run_date"] = date_text

    month = _month_key(date_text)
    if month == STATE["last_month"]:
        return
    STATE["last_month"] = month

    active = _active_symbols(date_text)
    try:
        ContextInfo.set_universe(active)
    except Exception:
        pass

    prices = _latest_prices(ContextInfo, date_text)
    if not prices:
        _log("no market data on {0}".format(date_text))
        return

    total_value = _portfolio_value(prices)
    _log("monthly check date={0} nav={1:.2f} cash={2:.2f}".format(date_text, total_value, STATE["cash"]))

    grid_traded = _grid_actions(ContextInfo, prices, total_value)
    total_value = _portfolio_value(prices)
    _initial_or_monthly_rebalance(ContextInfo, prices, total_value, date_text, skip_symbols=grid_traded)

    # Refresh anchor each month after decisions; grid levels are kept.
    for symbol, row in prices.items():
        STATE["anchor"][symbol] = row["close"]


def init(ContextInfo):
    try:
        ContextInfo.set_universe(_active_symbols(BACKTEST_START_DATE))
    except Exception:
        pass
    for symbol in _symbols():
        STATE["pos"].setdefault(symbol, 0)
        STATE["grid_level"].setdefault(symbol, 0)
    _log("strategy init")
    _log("symbols={0}".format(",".join(_symbols())))
    _log("ENABLE_ORDER={0}; run in QMT backtest first".format(ENABLE_ORDER))


def handlebar(ContextInfo):
    _run_monthly(ContextInfo)
