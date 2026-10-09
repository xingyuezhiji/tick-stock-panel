# Live Trading Console Design

## Goal

Build a `/live` trading console for TSP that turns strategy screening results into actionable buy and sell lists. V1 executes through the existing paper trading account only. QMT and PTrade are represented as disabled broker adapters until explicit configuration, risk checks, and account verification are added.

## Scope

V1 includes:

- Strategy candidate pool: run one strategy for a selected date and show the selected stocks.
- Buy actions: one-click submit buy orders for selected candidates that are not already held.
- Buffer pool check: compare current holdings against a strategy buffer pool and identify holdings that have fallen out.
- Sell actions: one-click submit sell orders for holdings that are outside the buffer pool and have available quantity.
- Broker selection: `paper` is enabled by default; `qmt` and `ptrade` return a clear disabled error.
- Manual control: every batch action requires a user click and confirmation in the UI.

V1 does not include:

- Real QMT/PTrade order submission.
- Automatic unattended live trading.
- Tick-level order routing, cancel/replace workflows, or broker-side fill reconciliation.
- A separate accounting system. Existing paper account files remain the only V1 ledger.

## Recommended Approach

Use the existing paper trading domain as the execution backend and add a thin live console layer on top.

This keeps the first release useful and testable: strategy output, buy list, buffer exit list, and batch order creation can be validated without touching real funds. It also preserves a clean path to real brokers by routing all actions through a broker adapter interface from day one.

Rejected alternatives:

- Direct QMT/PTrade integration in V1: too many production concerns land at once, including credentials, account binding, order status, fills, reconciliation, and kill-switch behavior.
- Adding buttons directly inside `/screener`: fast to implement, but the account, holdings, buffer pool, broker, and order result state would be scattered across unrelated pages.

## Backend Design

Create `backend/app/strategy/live.py` for domain logic.

Responsibilities:

- Load and validate a strategy.
- Run the strategy through existing `ScreenerService` and `StrategyEngine`.
- Rank returned rows using the strategy result order.
- Split rows into buy pool and buffer pool by request parameters.
- Load the selected paper account overview.
- Build two normalized lists:
  - candidate rows: symbol, name, rank, score, price fields, `held_qty`, `in_position`, `suggested_action`.
  - holding rows: symbol, qty, available_qty, avg_cost, last_price, pnl, pnl_pct, `in_buffer`, `suggested_action`.
- Dispatch batch orders through a broker adapter.

Create `backend/app/strategy/live_brokers.py`.

Broker contract:

```python
class LiveBroker(Protocol):
    id: str
    label: str
    enabled: bool

    def create_order(
        self,
        data_dir: Path,
        *,
        account_id: str,
        symbol: str,
        side: Literal["buy", "sell"],
        qty: int | None = None,
        amount: float | None = None,
        order_type: Literal["market", "next_open", "close"] = "next_open",
        ref_price: float | None = None,
    ) -> tuple[dict | None, str | None]:
        ...
```

Adapters:

- `PaperBroker`: calls `paper.create_order()` and uses current repository asset type resolution where available.
- `DisabledBroker("qmt")`: always returns `QMT broker 未配置，当前版本不会发送真实委托`.
- `DisabledBroker("ptrade")`: always returns `PTrade broker 未配置，当前版本不会发送真实委托`.

Create `backend/app/api/live.py`.

Endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/live/brokers` | Return broker availability and labels. |
| `GET` | `/api/live/strategy-pool` | Return strategy buy pool, buffer pool, and holding comparison. |
| `POST` | `/api/live/orders/buy-selected` | Create buy orders for selected candidate symbols. |
| `POST` | `/api/live/orders/sell-out-of-buffer` | Create sell orders for holdings outside the buffer pool. |

`GET /api/live/strategy-pool` query fields:

- `strategy_id`: required.
- `account`: default `default`.
- `broker`: default `paper`.
- `as_of`: optional date; default latest available date.
- `asset_type`: default `stock`.
- `timeframe`: default `1d`.
- `top_n`: default strategy `limit` or 30.
- `buffer_n`: default max(`top_n`, strategy limit or 45).

`POST /api/live/orders/buy-selected` body:

```json
{
  "strategy_id": "ai_muzcgqf1",
  "symbols": ["000001.SZ"],
  "account": "default",
  "broker": "paper",
  "as_of": "2026-09-24",
  "asset_type": "stock",
  "timeframe": "1d",
  "top_n": 30,
  "buffer_n": 45,
  "size_mode": "fixed_amount",
  "amount_per_symbol": 10000,
  "order_type": "next_open"
}
```

`POST /api/live/orders/sell-out-of-buffer` body:

```json
{
  "strategy_id": "ai_muzcgqf1",
  "symbols": ["000001.SZ"],
  "account": "default",
  "broker": "paper",
  "as_of": "2026-09-24",
  "asset_type": "stock",
  "timeframe": "1d",
  "top_n": 30,
  "buffer_n": 45,
  "order_type": "next_open"
}
```

Both mutation endpoints return:

```json
{
  "broker": "paper",
  "created": [],
  "skipped": [],
  "errors": []
}
```

Skipped rows are explicit and machine-readable:

- `already_held`
- `not_in_buy_pool`
- `still_in_buffer`
- `no_available_qty`
- `broker_disabled`
- `invalid_symbol`

## Frontend Design

Add `frontend/src/pages/Live.tsx` and route `/live`.

Page layout:

- Header: broker selector, account selector, strategy selector, date, TopN, BufferN, order type, fixed buy amount.
- Candidate table: strategy-selected stocks with rank, symbol, name, score, price/change fields if available, held status, checkbox, buy button.
- Holding buffer table: current holdings with qty, available_qty, pnl, `in_buffer`, checkbox, sell button.
- Batch actions: buy selected candidates and sell selected out-of-buffer holdings. Buttons open a confirmation modal with symbols, estimated amount/quantity, broker, and order type.
- Result panel: created orders, skipped rows, and errors after each batch action.

UI safety:

- The default broker badge says `模拟盘`.
- QMT/PTrade appear disabled with a tooltip-like explanation.
- Batch buttons are disabled when no valid symbols are selected.
- The confirmation modal uses plain language and shows that V1 will create simulated orders only.

Route/menu changes:

- `frontend/src/router.tsx`: lazy-load `Live` and add `/live`.
- `frontend/src/components/Layout.tsx`: add nav item `实盘` with a trading icon.
- `frontend/src/pages/settings/MenuSettings.tsx`: add `/live` to configurable built-in menu entries.

## Risk Controls

- Default execution path is `paper`.
- QMT/PTrade do not submit orders in V1.
- Server revalidates symbols against the latest generated pool before creating orders; the client cannot submit arbitrary symbols as strategy buys.
- Server revalidates buffer membership before selling; only holdings outside buffer are sellable by the batch sell endpoint.
- Sell uses `available_qty`, not total quantity, to respect T+1 constraints already modeled by paper trading.
- No endpoint places orders without explicit user request.
- Frozen paper accounts continue to reject orders through the existing `paper.create_order()` checks.

## Testing

Backend tests:

- `GET /api/live/brokers` returns `paper` enabled and `qmt`/`ptrade` disabled.
- `GET /api/live/strategy-pool` returns buy candidates and marks current holdings as in/out of buffer.
- Buy endpoint skips held symbols and symbols outside the buy pool.
- Sell endpoint skips symbols still inside buffer and holdings with zero available quantity.
- Disabled broker returns no created orders and a clear error.

Frontend validation:

- TypeScript build passes.
- `/live` loads with strategy/account controls.
- Candidate buy and buffer sell buttons call the expected API methods.
- Disabled broker options cannot be submitted.

## Rollout

1. Implement backend live domain, broker adapters, API routes, and tests.
2. Add frontend API types and `/live` page.
3. Register route and menu.
4. Run backend tests plus frontend build.
5. Start the local app and manually verify `/live` with the existing paper account.
6. Commit and push after verification.
