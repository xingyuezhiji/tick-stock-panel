#encoding:gbk
# -*- coding: utf-8 -*-
"""QMT HTTP order-plan preview strategy.

Copy this file into QMT's Python strategy editor. It fetches the latest TSP
order plan over HTTP and prints pending orders in QMT logs. This preview version
does not submit orders.
"""
import codecs
import json
import socket
import time
import urllib.parse


def _install_ascii_idna_codec():
    """QMT embedded Python may miss encodings.idna.

    socket/getaddrinfo asks Python's codec registry for "idna" even for ASCII
    hosts like 127.0.0.1. This tiny fallback is enough for the ASCII-only local
    URLs used by this preview script.
    """
    try:
        codecs.lookup("idna")
        return
    except LookupError:
        pass

    def ascii_idna_encode(input_text, errors="strict"):
        if isinstance(input_text, bytes):
            return input_text, len(input_text)
        return input_text.encode("ascii", errors), len(input_text)

    def ascii_idna_decode(input_bytes, errors="strict"):
        if isinstance(input_bytes, str):
            return input_bytes, len(input_bytes)
        return input_bytes.decode("ascii", errors), len(input_bytes)

    def search_codec(name):
        if name.replace("_", "-").lower() != "idna":
            return None
        return codecs.CodecInfo(
            name="idna",
            encode=ascii_idna_encode,
            decode=ascii_idna_decode,
        )

    codecs.register(search_codec)


_install_ascii_idna_codec()


TSP_BASE_URLS = [
    "http://127.0.0.1:3018",
    "http://localhost:3018",
    "http://host.docker.internal:3018",
]

# Leave empty to use the enabled strategy-follow rule bound to ACCOUNT.
STRATEGY_ID = ""
ACCOUNT = "default"
TOP_N = 30
BUFFER_N = 45
AMOUNT_PER_SYMBOL = 10000
INCLUDE_SELLS = True

# Avoid log spam in QMT. Set to 0 to print every time handlebar runs.
REFRESH_INTERVAL_SECONDS = 30

_LAST_FETCH_AT = 0.0
_LAST_PLAN_ID = None
_WORKING_BASE_URL = None
_RESOLVED_STRATEGY_ID = None


def _log(message: str) -> None:
    print("[TSP-HTTP]", message)


def _build_auto_rules_url(base_url):
    query = urllib.parse.urlencode({
        "account": ACCOUNT,
    })
    return base_url.rstrip("/") + "/api/paper/auto_rules?" + query


def _build_url(base_url, strategy_id):
    query = urllib.parse.urlencode({
        "strategy_id": strategy_id,
        "account": ACCOUNT,
        "top_n": TOP_N,
        "buffer_n": BUFFER_N,
        "amount_per_symbol": AMOUNT_PER_SYMBOL,
        "include_sells": str(bool(INCLUDE_SELLS)).lower(),
    })
    return base_url.rstrip("/") + "/api/live/qmt/order-plan/latest?" + query


def _resolve_strategy_id(base_url):
    if STRATEGY_ID:
        return STRATEGY_ID
    data = _fetch_json(_build_auto_rules_url(base_url))
    rules = data.get("rules") or []
    matches = []
    for rule in rules:
        if not rule.get("enabled"):
            continue
        if rule.get("match_kind") != "strategy" or rule.get("side") != "follow":
            continue
        match_id = rule.get("match_id")
        if match_id and match_id not in matches:
            matches.append(match_id)
    if not matches:
        raise RuntimeError("No enabled strategy-follow rule for account=%s" % ACCOUNT)
    if len(matches) > 1:
        _log("multiple account strategies found, use first: %s" % ",".join(matches))
    return matches[0]


def _parse_http_url(url):
    if not url.startswith("http://"):
        raise ValueError("Only http:// URL is supported: %s" % url)
    rest = url[len("http://"):]
    slash = rest.find("/")
    if slash < 0:
        host_port = rest
        path = "/"
    else:
        host_port = rest[:slash]
        path = rest[slash:]
    if ":" in host_port:
        host, port_text = host_port.rsplit(":", 1)
        port = int(port_text)
    else:
        host = host_port
        port = 80
    return host, port, path


def _fetch_json(url, timeout=5):
    # QMT embedded Python may miss the "idna" codec used by urllib.request.
    # Use a small raw HTTP client to avoid that dependency.
    host, port, path = _parse_http_url(url)
    request = (
        "GET %s HTTP/1.1\r\n"
        "Host: %s:%s\r\n"
        "Accept: application/json\r\n"
        "User-Agent: QMT-TSP-HTTP-Preview/0.2\r\n"
        "Connection: close\r\n"
        "\r\n"
    ) % (path, host, port)

    sock = socket.create_connection((host, port), timeout)
    try:
        sock.sendall(request.encode("ascii"))
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()

    raw = b"".join(chunks)
    header_end = raw.find(b"\r\n\r\n")
    if header_end < 0:
        raise RuntimeError("Invalid HTTP response")
    header = raw[:header_end].decode("iso-8859-1", "replace")
    body = raw[header_end + 4:]
    status_line = header.split("\r\n", 1)[0]
    parts = status_line.split(" ")
    status = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
    if status < 200 or status >= 300:
        text = body[:500].decode("utf-8", "replace")
        raise RuntimeError("HTTP %s: %s" % (status, text))

    # The local TSP API returns a normal JSON body without chunked encoding.
    return json.loads(body.decode("utf-8"))


def fetch_tsp_order_plan():
    global _WORKING_BASE_URL, _RESOLVED_STRATEGY_ID

    candidates = []
    if _WORKING_BASE_URL:
        candidates.append(_WORKING_BASE_URL)
    candidates.extend([url for url in TSP_BASE_URLS if url != _WORKING_BASE_URL])

    last_error = None
    for base_url in candidates:
        try:
            strategy_id = _resolve_strategy_id(base_url)
            url = _build_url(base_url, strategy_id)
            data = _fetch_json(url)
            _WORKING_BASE_URL = base_url
            _RESOLVED_STRATEGY_ID = strategy_id
            return data
        except Exception as exc:
            last_error = exc
            url = base_url.rstrip("/") + "/api/live/qmt/order-plan/latest"
            _log("connect failed %s: %s" % (url, exc))
    raise RuntimeError("Cannot connect to TSP: %s" % last_error)


def preview_plan(force=False):
    global _LAST_FETCH_AT, _LAST_PLAN_ID

    now = time.time()
    if not force and REFRESH_INTERVAL_SECONDS > 0 and now - _LAST_FETCH_AT < REFRESH_INTERVAL_SECONDS:
        return
    _LAST_FETCH_AT = now

    try:
        plan = fetch_tsp_order_plan()
    except Exception as exc:
        _log("fetch TSP plan failed: %s" % exc)
        return

    plan_id = plan.get("plan_id") or ""
    if not force and plan_id == _LAST_PLAN_ID:
        return
    _LAST_PLAN_ID = plan_id

    plan_strategy = plan.get("strategy_id", "")
    plan_account = plan.get("account", "")
    expected_strategy = _RESOLVED_STRATEGY_ID or STRATEGY_ID
    if plan_id != "none" and (plan_strategy != expected_strategy or plan_account != ACCOUNT):
        _log("plan mismatch: expected strategy=%s account=%s, got strategy=%s account=%s plan_id=%s" % (
            expected_strategy,
            ACCOUNT,
            plan_strategy,
            plan_account,
            plan_id,
        ))
        _log("skip mismatched plan; please generate QMT preview plan for this strategy/account in TSP /live.")
        return

    orders = plan.get("orders") or []
    skipped = plan.get("skipped") or []
    _log("plan_id=%s strategy=%s date=%s" % (
        plan_id,
        plan.get("strategy_id", ""),
        plan.get("trade_date", ""),
    ))
    _log("orders=%d skipped=%d" % (len(orders), len(skipped)))
    for order in orders:
        side = "BUY" if order.get("side") == "buy" else "SELL"
        reason = order.get("reason") or ""
        _log("%s %s %s qty=%s ref=%s %s" % (
            side,
            order.get("symbol", ""),
            order.get("name", ""),
            order.get("qty", ""),
            order.get("ref_price", ""),
            reason,
        ))
    if skipped:
        sample = ", ".join(
            "%s:%s" % (row.get("symbol", ""), row.get("reason", ""))
            for row in skipped[:10]
        )
        _log("skipped sample: %s" % sample)
    _log("preview mode: no real order will be submitted.")


def init(ContextInfo):
    del ContextInfo
    _log("strategy init, socket idna fallback installed")
    _log("strategy_id=%s account=%s top_n=%s buffer_n=%s" % (STRATEGY_ID or "auto", ACCOUNT, TOP_N, BUFFER_N))
    preview_plan(force=True)


def handlebar(ContextInfo):
    del ContextInfo
    preview_plan(force=False)


if __name__ == "__main__":
    while True:
        preview_plan(force=False)
        time.sleep(3)
