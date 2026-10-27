#encoding:gbk
"""QMT port of TSP AlphaGPT round935 c12 jump delay.

Copy this file into QMT's Python strategy editor and run it in backtest mode.

This is a practical QMT approximation of the TSP matrix-native strategy:
- Weekly rotation.
- Buy top N by AlphaGPT score.
- Hold buffer N; sell positions outside the buffer.
- Liquidity filter: average amount over 20 bars >= 30m.
- Stop loss and trailing stop are included.

The exact TSP implementation ranks a full market matrix. QMT has different
runtime APIs, so this script rebuilds the needed features from daily bars inside
QMT and uses robust cross-sectional normalization on the current universe.
"""

import math
import time


ENABLE_ORDER = True
ACCOUNT_ID = "test"
STRATEGY_NAME = "alphagpt_round935_c12_qmt"

N_BUY = 30
N_HOLD = 45
MIN_LISTED_DAYS = 60
AMOUNT_WINDOW = 20
MIN_AVG_AMOUNT = 30000000.0
LOOKBACK = 95
MAX_UNIVERSE = 300
BATCH_SIZE = 80
MAX_NEW_BUYS_PER_RUN = 30
MIN_ORDER_VALUE = 5000.0
ORDER_CASH_SAFETY = 0.90
MAX_POSITION_COUNT = 30

STOP_LOSS = -0.10
TRAILING_STOP = -0.12

# ASCII-only source. This is "hu shen A gu" as unicode escapes.
UNIVERSE_SECTORS = ["\u6caa\u6df1A\u80a1", "A\u80a1"]

BUY_OP = 23
SELL_OP = 24
ORDER_BY_SHARES = 1101
PRICE_LATEST = 5
QUICK_TRADE = 2


STATE = {
    "cash": 1000000.0,
    "pos": {},
    "cost": {},
    "high": {},
    "last_week": "",
    "last_run_date": "",
}

TRADE_LOG = []


def _log(msg):
    print("[AGPT935]", msg)


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
    try:
        tag = ContextInfo.get_bar_timetag(ContextInfo.barpos)
        try:
            text = ContextInfo.timetag_to_datetime(tag, "%Y%m%d")
        except Exception:
            text = time.strftime("%Y%m%d", time.localtime(float(tag) / 1000.0))
        return str(text)[:8]
    except Exception:
        return time.strftime("%Y%m%d")


def _week_key(date_text):
    try:
        y = int(date_text[:4])
        m = int(date_text[4:6])
        d = int(date_text[6:8])
        return time.strftime("%Y%W", time.strptime("%04d%02d%02d" % (y, m, d), "%Y%m%d"))
    except Exception:
        return str(date_text)[:6]


def _series_from_raw(raw, symbol, field):
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
    try:
        if hasattr(obj, "__getitem__") and symbol in getattr(obj, "columns", []):
            return [_safe_float(v) for v in list(obj[symbol].values) if _safe_float(v) is not None]
    except Exception:
        pass
    try:
        if hasattr(obj, "__getitem__") and field in getattr(obj, "columns", []):
            return [_safe_float(v) for v in list(obj[field].values) if _safe_float(v) is not None]
    except Exception:
        pass
    try:
        if hasattr(obj, "values") and not isinstance(obj, dict):
            return [_safe_float(v) for v in list(obj.values) if _safe_float(v) is not None]
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


def _get_field_series(ContextInfo, symbol, field, count, end_date):
    last_error = None
    for call_kind in (1, 2, 3):
        try:
            if call_kind == 1:
                raw = ContextInfo.get_market_data_ex([field], [symbol], period="1d", count=count, end_time=end_date)
            elif call_kind == 2:
                raw = ContextInfo.get_market_data([field], stock_code=[symbol], period="1d", count=count, end_time=end_date)
            else:
                raw = ContextInfo.get_market_data([field], [symbol], "1d", "", end_date, count)
            out = _series_from_raw(raw, symbol, field)
            if out:
                return out
        except Exception as exc:
            last_error = exc
    return []


def _get_bars(ContextInfo, symbol, end_date):
    close = _get_field_series(ContextInfo, symbol, "close", LOOKBACK, end_date)
    volume = _get_field_series(ContextInfo, symbol, "volume", LOOKBACK, end_date)
    amount = _get_field_series(ContextInfo, symbol, "amount", LOOKBACK, end_date)
    if len(close) < MIN_LISTED_DAYS or len(volume) < MIN_LISTED_DAYS:
        return None
    n = min(len(close), len(volume), len(amount) if amount else len(close))
    close = close[-n:]
    volume = volume[-n:]
    if amount:
        amount = amount[-n:]
    else:
        amount = [close[i] * volume[i] for i in range(n)]
    return {"close": close, "volume": volume, "amount": amount}


def _bars_from_series(close, volume, amount):
    if len(close) < MIN_LISTED_DAYS or len(volume) < MIN_LISTED_DAYS:
        return None
    n = min(len(close), len(volume), len(amount) if amount else len(close))
    close = close[-n:]
    volume = volume[-n:]
    if amount:
        amount = amount[-n:]
    else:
        amount = [close[i] * volume[i] for i in range(n)]
    return {"close": close, "volume": volume, "amount": amount}


def _get_bars_batch(ContextInfo, symbols, end_date):
    out = {}
    if not symbols:
        return out
    fields = ["close", "volume", "amount"]
    for start in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[start:start + BATCH_SIZE]
        raw = None
        try:
            raw = ContextInfo.get_market_data_ex(fields, batch, period="1d", count=LOOKBACK, end_time=end_date)
        except Exception:
            raw = None
        if raw is None:
            for symbol in batch:
                bars = _get_bars(ContextInfo, symbol, end_date)
                if bars:
                    out[symbol] = bars
            continue
        for symbol in batch:
            close = _series_from_raw(raw, symbol, "close")
            volume = _series_from_raw(raw, symbol, "volume")
            amount = _series_from_raw(raw, symbol, "amount")
            bars = _bars_from_series(close, volume, amount)
            if bars:
                out[symbol] = bars
        _log("loaded bars batch {0}-{1}, usable={2}".format(start + 1, min(start + len(batch), len(symbols)), len(out)))
    return out


def _is_tradeable_today(bars):
    if not bars:
        return False
    close = bars.get("close") or []
    volume = bars.get("volume") or []
    amount = bars.get("amount") or []
    if len(close) < 2 or len(volume) < 2:
        return False
    price = _safe_float(close[-1])
    vol = _safe_float(volume[-1], 0.0)
    amt = _safe_float(amount[-1], 0.0) if amount else 0.0
    if price is None or price <= 0:
        return False
    if vol <= 0 and amt <= 0:
        return False
    # Skip likely one-price limit-up/limit-down or stale bars. These are hard
    # for QMT to fill in backtest and often produce silent passorder rejects.
    prev = _safe_float(close[-2])
    if prev is not None and prev > 0:
        ret = price / prev - 1.0
        if ret >= 0.095 or ret <= -0.095:
            return False
    return True


def _mean(xs):
    vals = [x for x in xs if x is not None and math.isfinite(x)]
    return sum(vals) / len(vals) if vals else None


def _corr(xs, ys, window):
    if len(xs) < window or len(ys) < window:
        return None
    x = xs[-window:]
    y = ys[-window:]
    mx = _mean(x)
    my = _mean(y)
    if mx is None or my is None:
        return None
    num = 0.0
    vx = 0.0
    vy = 0.0
    for i in range(window):
        dx = x[i] - mx
        dy = y[i] - my
        num += dx * dy
        vx += dx * dx
        vy += dy * dy
    den = math.sqrt(vx * vy)
    if den <= 1e-12:
        return 0.0
    return num / den


def _ema_last(xs, span):
    if not xs:
        return None
    alpha = 2.0 / (float(span) + 1.0)
    out = xs[0]
    for x in xs[1:]:
        out = alpha * x + (1.0 - alpha) * out
    return out


def _median(xs):
    vals = sorted([x for x in xs if x is not None and math.isfinite(x)])
    n = len(vals)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return vals[mid]
    return 0.5 * (vals[mid - 1] + vals[mid])


def _robust_norm_map(raw_map):
    vals = list(raw_map.values())
    med = _median(vals)
    mad = _median([abs(v - med) for v in vals if v is not None and math.isfinite(v)])
    if mad <= 1e-9:
        mad = 1.0
    out = {}
    for symbol, value in raw_map.items():
        if value is None or not math.isfinite(value):
            out[symbol] = 0.0
        else:
            z = (value - med) / mad
            out[symbol] = max(-5.0, min(5.0, z))
    return out


def _score_universe(ContextInfo, symbols, end_date):
    raw = {}
    latest = {}
    avg_amounts = {}
    bars_map = _get_bars_batch(ContextInfo, symbols, end_date)
    for symbol, bars in bars_map.items():
        if not bars:
            continue
        if not _is_tradeable_today(bars):
            continue
        close = bars["close"]
        volume = bars["volume"]
        amount = bars["amount"]
        avg_amount = _mean(amount[-AMOUNT_WINDOW:])
        if avg_amount is None or avg_amount < MIN_AVG_AMOUNT:
            continue
        ema60 = _ema_last(close[-60:], 60)
        if ema60 is None or ema60 <= 0:
            continue
        ca20 = _corr(close, amount, 20)
        cv30 = _corr(close, volume, 30)
        if ca20 is None or cv30 is None:
            continue
        ma60_bias = close[-1] / ema60 - 1.0
        raw[symbol] = {
            "CA_CORR20_LOW": -ca20,
            "CV_CORR30_LOW": -cv30,
            "MA60_BIAS_LOW": -ma60_bias,
        }
        latest[symbol] = close[-1]
        avg_amounts[symbol] = avg_amount

    if not raw:
        return [], {}

    norm_ca = _robust_norm_map(dict((s, v["CA_CORR20_LOW"]) for s, v in raw.items()))
    norm_cv = _robust_norm_map(dict((s, v["CV_CORR30_LOW"]) for s, v in raw.items()))
    norm_ma = _robust_norm_map(dict((s, v["MA60_BIAS_LOW"]) for s, v in raw.items()))

    scored = []
    for symbol in raw.keys():
        cv = norm_cv.get(symbol, 0.0)
        ca = norm_ca.get(symbol, 0.0)
        ma = norm_ma.get(symbol, 0.0)
        max3 = max(cv, ca, ma)
        neg = -max3
        gate1 = max3 if ca > 0 else ma
        jump1 = max(0.0, neg - 3.0)
        gate2 = jump1 if cv > 0 else gate1
        jump2 = max(0.0, gate2 - 3.0)
        # Extra bias keeps the score useful when JUMP is sparse in QMT's
        # single-date approximation.
        score = jump2 * 10.0 + 0.45 * cv + 0.35 * ca + 0.20 * ma
        scored.append((score, symbol, latest[symbol], avg_amounts[symbol]))
    scored.sort(reverse=True)
    prices = dict((symbol, price) for _, symbol, price, _ in scored)
    return scored, prices


def _get_universe(ContextInfo, end_date):
    symbols = []
    for sector in UNIVERSE_SECTORS:
        try:
            got = ContextInfo.get_stock_list_in_sector(sector)
            if got:
                symbols.extend([str(x) for x in got])
        except Exception:
            pass
    # Fallback: QMT may use current universe from the default symbol only.
    if not symbols:
        symbols = []
    seen = set()
    clean = []
    for symbol in symbols:
        if symbol in seen:
            continue
        seen.add(symbol)
        if not (symbol.endswith(".SH") or symbol.endswith(".SZ")):
            continue
        # Exclude Beijing board and obvious indexes.
        if symbol.startswith("8") or symbol.startswith("4") or symbol.startswith("9"):
            continue
        clean.append(symbol)
    return clean[:MAX_UNIVERSE]


def _log_trade(date_text, side, symbol, qty, price, reason):
    amount = float(qty) * float(price)
    row = {
        "date": str(date_text),
        "side": side.upper(),
        "symbol": symbol,
        "qty": int(qty),
        "price": float(price),
        "amount": amount,
        "reason": reason,
        "cash": float(STATE["cash"]),
        "pos": int(STATE["pos"].get(symbol, 0)),
    }
    TRADE_LOG.append(row)
    print(
        "[TRADE] date={0} side={1} symbol={2} qty={3} price={4:.4f} amount={5:.2f} "
        "reason={6} cash={7:.2f} pos={8}".format(
            row["date"], row["side"], row["symbol"], row["qty"], row["price"],
            row["amount"], row["reason"], row["cash"], row["pos"],
        )
    )


def _send_order(ContextInfo, date_text, symbol, side, qty, price, reason):
    qty = _lot_qty(qty)
    if qty <= 0 or price is None or price <= 0:
        return False
    if qty * price < MIN_ORDER_VALUE:
        return False
    if side == "buy":
        if len([s for s, q in STATE["pos"].items() if q > 0]) >= MAX_POSITION_COUNT and int(STATE["pos"].get(symbol, 0)) <= 0:
            return False
        if qty * price > STATE["cash"]:
            qty = _lot_qty((STATE["cash"] * ORDER_CASH_SAFETY) / price)
        if qty <= 0 or qty * price < MIN_ORDER_VALUE:
            return False
        op = BUY_OP
    else:
        hold = int(STATE["pos"].get(symbol, 0))
        if hold <= 0:
            return False
        qty = min(qty, hold)
        qty = _lot_qty(qty)
        if qty <= 0:
            return False
        op = SELL_OP

    _log("{0} {1} qty={2} ref={3:.4f} {4}".format(side.upper(), symbol, qty, price, reason))
    if not ENABLE_ORDER:
        return False
    try:
        passorder(op, ORDER_BY_SHARES, ACCOUNT_ID, symbol, PRICE_LATEST, 0, qty, STRATEGY_NAME, QUICK_TRADE, reason, ContextInfo)
    except Exception as exc:
        _log("passorder failed for {0}: {1}".format(symbol, exc))
        return False

    if side == "buy":
        old_qty = int(STATE["pos"].get(symbol, 0))
        old_cost = float(STATE["cost"].get(symbol, 0.0))
        new_qty = old_qty + qty
        STATE["cash"] -= qty * price
        STATE["pos"][symbol] = new_qty
        STATE["cost"][symbol] = ((old_cost * old_qty) + qty * price) / float(new_qty)
        STATE["high"][symbol] = max(float(STATE["high"].get(symbol, price)), price)
    else:
        STATE["cash"] += qty * price
        STATE["pos"][symbol] = int(STATE["pos"].get(symbol, 0)) - qty
        if STATE["pos"][symbol] <= 0:
            STATE["pos"][symbol] = 0
            STATE["cost"][symbol] = 0.0
            STATE["high"][symbol] = 0.0
    _log_trade(date_text, side, symbol, qty, price, reason)
    return True


def _risk_sells(ContextInfo, date_text, prices):
    for symbol, qty in list(STATE["pos"].items()):
        if qty <= 0:
            continue
        price = prices.get(symbol)
        if price is None or price <= 0:
            continue
        high = max(float(STATE["high"].get(symbol, price)), price)
        STATE["high"][symbol] = high
        cost = float(STATE["cost"].get(symbol, price))
        if cost > 0 and price / cost - 1.0 <= STOP_LOSS:
            _send_order(ContextInfo, date_text, symbol, "sell", qty, price, "stop_loss")
            continue
        if high > 0 and price / high - 1.0 <= TRAILING_STOP:
            _send_order(ContextInfo, date_text, symbol, "sell", qty, price, "trailing_stop")


def _run_weekly(ContextInfo):
    date_text = _bar_date(ContextInfo)
    if date_text == STATE["last_run_date"]:
        return
    STATE["last_run_date"] = date_text
    week = _week_key(date_text)
    if week == STATE["last_week"]:
        return
    STATE["last_week"] = week

    universe = _get_universe(ContextInfo, date_text)
    if not universe:
        _log("empty universe; check QMT sector name")
        return
    try:
        ContextInfo.set_universe(universe[:200])
    except Exception:
        pass

    scored, prices = _score_universe(ContextInfo, universe, date_text)
    if not scored:
        _log("no scored stocks on {0}".format(date_text))
        return

    top = [x[1] for x in scored[:N_BUY]]
    buffer_set = set([x[1] for x in scored[:N_HOLD]])
    _log("weekly date={0} universe={1} scored={2} top1={3}".format(
        date_text, len(universe), len(scored), top[0] if top else "",
    ))

    _risk_sells(ContextInfo, date_text, prices)

    for symbol, qty in list(STATE["pos"].items()):
        if qty > 0 and symbol not in buffer_set:
            price = prices.get(symbol)
            if price is not None:
                _send_order(ContextInfo, date_text, symbol, "sell", qty, price, "buffer_exit")

    current = set([s for s, q in STATE["pos"].items() if q > 0])
    need_buy = [s for s in top if s not in current]
    if not need_buy:
        return
    open_slots = max(0, MAX_POSITION_COUNT - len(current))
    if open_slots <= 0:
        return
    slots = min(MAX_NEW_BUYS_PER_RUN, open_slots, len(need_buy))
    cash_per = STATE["cash"] / float(max(1, slots))
    for symbol in need_buy[:slots]:
        price = prices.get(symbol)
        if price is None or price <= 0:
            continue
        qty = _lot_qty(cash_per / price)
        _send_order(ContextInfo, date_text, symbol, "buy", qty, price, "top30_entry")


def init(ContextInfo):
    _log("strategy init")
    _log("id=ai_alphagpt_round935_c12_jump_delay qmt approximate")
    _log("N_BUY={0} N_HOLD={1} ENABLE_ORDER={2}".format(N_BUY, N_HOLD, ENABLE_ORDER))


def handlebar(ContextInfo):
    _run_weekly(ContextInfo)
