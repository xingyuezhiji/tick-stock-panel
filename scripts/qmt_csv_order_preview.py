"""QMT CSV order preview strategy.

Copy this file into QMT's Python strategy editor. It reads a CSV order plan
exported by TSP and prints the pending orders in QMT logs. This preview version
does not submit orders.

Expected CSV columns:
symbol,side,qty,price_type,reason

Optional columns:
confirmed,status,remark
"""
import csv
import os
import time


# Change this to the path that QMT/CrossOver can read.
# CrossOver usually maps the macOS home directory under Z:\Users\<name>\...
CSV_PATH = r"Z:\Users\bytedance\Downloads\tsp_order_plan.csv"

# Only rows with confirmed=1/yes/true/y are shown when this is True.
# Keep False while testing the file path and CSV format.
REQUIRE_CONFIRMED = False

# Skip rows whose status is not empty/pending/new.
SKIP_NON_PENDING = True

VALID_SIDES = {"buy", "sell", "买入", "卖出"}
BUY_VALUES = {"buy", "买入"}
SELL_VALUES = {"sell", "卖出"}
PENDING_VALUES = {"", "pending", "new", "待执行", "待下单"}
CONFIRMED_VALUES = {"1", "yes", "true", "y", "确认", "已确认"}

_LAST_SIGNATURE = None


def _log(message):
    print("[TSP-CSV]", message)


def _norm(value):
    return str(value or "").strip()


def _read_csv_rows(path):
    encodings = ("utf-8-sig", "utf-8", "gbk")
    last_error = None
    for encoding in encodings:
        try:
            with open(path, "r", encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return []


def _normalize_symbol(symbol):
    """Keep TSP symbols compatible with QMT: 603030.SH / 300923.SZ."""
    value = _norm(symbol).upper()
    if "." in value:
        code, market = value.split(".", 1)
        return f"{code}.{market}"
    if value.startswith(("60", "68", "51", "56", "58")):
        return f"{value}.SH"
    if value.startswith(("00", "30", "15", "12")):
        return f"{value}.SZ"
    return value


def _row_status(row):
    symbol = _normalize_symbol(row.get("symbol") or row.get("代码") or row.get("证券代码"))
    side_raw = _norm(row.get("side") or row.get("方向")).lower()
    qty_raw = _norm(row.get("qty") or row.get("数量") or row.get("volume"))
    price_type = _norm(row.get("price_type") or row.get("价格类型")) or "latest"
    reason = _norm(row.get("reason") or row.get("原因"))
    status = _norm(row.get("status") or row.get("状态")).lower()
    confirmed = _norm(row.get("confirmed") or row.get("确认")).lower()

    if not symbol:
        return None, "missing_symbol"
    if side_raw not in VALID_SIDES:
        return None, f"invalid_side:{side_raw or '<empty>'}"
    try:
        qty = int(float(qty_raw))
    except Exception:
        return None, f"invalid_qty:{qty_raw or '<empty>'}"
    if qty <= 0:
        return None, f"invalid_qty:{qty}"
    if qty % 100 != 0:
        return None, f"qty_not_lot_size:{qty}"
    if REQUIRE_CONFIRMED and confirmed not in CONFIRMED_VALUES:
        return None, "not_confirmed"
    if SKIP_NON_PENDING and status not in PENDING_VALUES:
        return None, f"status_not_pending:{status}"

    side = "buy" if side_raw in BUY_VALUES else "sell"
    return {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price_type": price_type,
        "reason": reason,
        "confirmed": confirmed,
        "status": status,
    }, None


def load_order_plan(path):
    rows = _read_csv_rows(path)
    orders = []
    skipped = []
    for idx, row in enumerate(rows, start=2):
        order, reason = _row_status(row)
        if order is None:
            skipped.append((idx, reason or "invalid_row"))
            continue
        orders.append(order)
    return orders, skipped


def preview_once():
    global _LAST_SIGNATURE

    if not os.path.exists(CSV_PATH):
        _log(f"CSV 不存在: {CSV_PATH}")
        return

    stat = os.stat(CSV_PATH)
    signature = (stat.st_mtime, stat.st_size)
    if signature == _LAST_SIGNATURE:
        return
    _LAST_SIGNATURE = signature

    try:
        orders, skipped = load_order_plan(CSV_PATH)
    except Exception as exc:
        _log(f"读取 CSV 失败: {exc}")
        return

    _log(f"读取清单: {CSV_PATH}")
    _log(f"待执行 {len(orders)} 条, 跳过 {len(skipped)} 条")
    for order in orders:
        side_label = "买入" if order["side"] == "buy" else "卖出"
        reason = f" | {order['reason']}" if order["reason"] else ""
        _log(f"{side_label} {order['symbol']} {order['qty']}股 price_type={order['price_type']}{reason}")

    if skipped:
        sample = ", ".join(f"L{line}:{reason}" for line, reason in skipped[:10])
        _log(f"跳过明细: {sample}")

    _log("预览模式: 当前脚本不会提交真实委托。确认清单无误后再开启执行版。")


def init(ContextInfo):
    _log("策略初始化")
    _log(f"CSV_PATH={CSV_PATH}")
    preview_once()


def handlebar(ContextInfo):
    # QMT will call this on each bar/tick depending on strategy settings.
    preview_once()


if __name__ == "__main__":
    while True:
        preview_once()
        time.sleep(3)
