# Live Trading Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/live` console that converts strategy candidates and buffer-pool exits into manual one-click paper orders, with QMT/PTrade disabled placeholders.

**Architecture:** Backend adds a small live domain that reuses `ScreenerService`, `StrategyEngine`, and paper accounting. A broker adapter boundary keeps V1 on paper while making real broker integration explicit later. Frontend adds one work-focused page and API bindings.

**Tech Stack:** FastAPI, Pydantic, existing TSP strategy/paper modules, React, TanStack Query, Vite, TypeScript.

---

## File Structure

- Create `backend/app/strategy/live_brokers.py`: broker registry, `PaperBroker`, disabled QMT/PTrade adapters.
- Create `backend/app/strategy/live.py`: strategy pool construction and batch order orchestration.
- Create `backend/app/api/live.py`: HTTP request/response models and live routes.
- Modify `backend/app/main.py`: import and include live router.
- Create `backend/tests/test_live_trading.py`: unit/API coverage for broker availability, pool comparison, and batch safeguards.
- Modify `frontend/src/lib/api.ts`: live types and request helpers.
- Create `frontend/src/pages/Live.tsx`: live trading console UI.
- Modify `frontend/src/router.tsx`: lazy route registration.
- Modify `frontend/src/components/Layout.tsx`: add nav item.
- Modify `frontend/src/pages/settings/MenuSettings.tsx`: add menu settings entry.

## Task 1: Backend Broker Boundary

**Files:**
- Create: `backend/app/strategy/live_brokers.py`

- [ ] **Step 1: Write the broker module**

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from app.strategy import paper

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "next_open", "close"]


class LiveBroker(Protocol):
    id: str
    label: str
    enabled: bool

    def create_order(self, data_dir: Path, *, account_id: str, symbol: str, side: OrderSide, qty: int | None = None, amount: float | None = None, order_type: OrderType = "next_open", asset_type: str = "stock", ref_price: float | None = None) -> tuple[dict | None, str | None]:
        ...


class PaperBroker:
    id = "paper"
    label = "模拟盘"
    enabled = True

    def create_order(self, data_dir: Path, *, account_id: str, symbol: str, side: OrderSide, qty: int | None = None, amount: float | None = None, order_type: OrderType = "next_open", asset_type: str = "stock", ref_price: float | None = None) -> tuple[dict | None, str | None]:
        return paper.create_order(data_dir, symbol, side, account_id=account_id, qty=qty, amount=amount, order_type=order_type, asset_type=asset_type, ref_price=ref_price, source="live")


class DisabledBroker:
    enabled = False

    def __init__(self, broker_id: str, label: str, message: str) -> None:
        self.id = broker_id
        self.label = label
        self.message = message

    def create_order(self, data_dir: Path, **kwargs) -> tuple[dict | None, str | None]:
        return None, self.message


BROKERS = {
    "paper": PaperBroker(),
    "qmt": DisabledBroker("qmt", "QMT", "QMT broker 未配置，当前版本不会发送真实委托"),
    "ptrade": DisabledBroker("ptrade", "PTrade", "PTrade broker 未配置，当前版本不会发送真实委托"),
}


def broker_summaries() -> list[dict]:
    return [{"id": b.id, "label": b.label, "enabled": b.enabled} for b in BROKERS.values()]


def get_broker(broker_id: str) -> LiveBroker:
    return BROKERS.get(broker_id) or BROKERS["paper"]
```

- [ ] **Step 2: Run import check**

Run: `cd backend && python -m py_compile app/strategy/live_brokers.py`
Expected: no output and exit code 0.

## Task 2: Backend Live Domain

**Files:**
- Create: `backend/app/strategy/live.py`

- [ ] **Step 1: Implement pool building and order batches**

Implement:

```python
build_strategy_pool(repo, engine, *, strategy_id, account_id, as_of, asset_type, timeframe, top_n, buffer_n)
buy_selected(data_dir, repo, engine, body)
sell_out_of_buffer(data_dir, repo, engine, body)
```

Rules:

- Reuse `ScreenerService.build_strategy_context()` and `engine.run()`.
- Use `strategy_config.load_override()` and params from overrides.
- Candidate rows are the first `top_n` strategy rows.
- Buffer symbols are the first `buffer_n` strategy rows.
- Holding rows come from `paper.overview(data_dir, account_id=account_id)`.
- Buy skips existing positions and non-candidate symbols.
- Sell skips symbols still in buffer or with `available_qty <= 0`.

- [ ] **Step 2: Run import check**

Run: `cd backend && python -m py_compile app/strategy/live.py`
Expected: no output and exit code 0.

## Task 3: Live API

**Files:**
- Create: `backend/app/api/live.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add FastAPI routes**

Routes:

```python
GET /api/live/brokers
GET /api/live/strategy-pool
POST /api/live/orders/buy-selected
POST /api/live/orders/sell-out-of-buffer
```

Use Pydantic models for request bodies. Convert `ValueError` to 400 or 404 where appropriate.

- [ ] **Step 2: Register router**

Add `from app.api import live` near other API imports and `app.include_router(live.router)` near the paper router.

- [ ] **Step 3: Run import check**

Run: `cd backend && python -m py_compile app/api/live.py app/main.py`
Expected: no output and exit code 0.

## Task 4: Backend Tests

**Files:**
- Create: `backend/tests/test_live_trading.py`

- [ ] **Step 1: Add focused tests**

Test these functions directly with fakes where possible:

```python
def test_brokers_expose_disabled_real_brokers(): ...
def test_strategy_pool_marks_holdings_outside_buffer(): ...
def test_buy_selected_skips_held_and_outside_pool(): ...
def test_sell_out_of_buffer_skips_buffer_members(): ...
```

- [ ] **Step 2: Run tests**

Run: `cd backend && pytest tests/test_live_trading.py -q`
Expected: all tests pass.

## Task 5: Frontend API

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add live interfaces**

Add `LiveBrokerSummary`, `LiveStrategyPool`, `LiveCandidateRow`, `LiveHoldingRow`, `LiveOrderBatchResult`, `LiveOrderSkipped`.

- [ ] **Step 2: Add methods**

Add:

```ts
liveBrokers()
liveStrategyPool(params)
liveBuySelected(body)
liveSellOutOfBuffer(body)
```

## Task 6: Frontend Page and Navigation

**Files:**
- Create: `frontend/src/pages/Live.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/pages/settings/MenuSettings.tsx`

- [ ] **Step 1: Build `/live` page**

Use existing table/button/modal style from `Paper.tsx`. Keep the page dense: controls at top, candidate table and holding table below, result panel at bottom.

- [ ] **Step 2: Register route and menu**

Add lazy `Live` import, `/live` route, nav item labeled `实盘`, and menu settings entry.

- [ ] **Step 3: Build frontend**

Run: `cd frontend && npm run build`
Expected: build succeeds.

## Task 7: End-to-End Verification and Commit

**Files:**
- All files above.

- [ ] **Step 1: Run backend compile/tests**

Run:

```bash
cd backend
python -m py_compile app/strategy/live_brokers.py app/strategy/live.py app/api/live.py app/main.py
pytest tests/test_live_trading.py -q
```

Expected: all pass.

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Check git diff**

Run: `git status --short && git diff --stat`
Expected: only intended live trading files plus existing unrelated dirty files are shown.

- [ ] **Step 4: Commit and push intended changes**

Stage only live trading files and the plan/spec docs:

```bash
git add backend/app/strategy/live_brokers.py backend/app/strategy/live.py backend/app/api/live.py backend/app/main.py backend/tests/test_live_trading.py frontend/src/lib/api.ts frontend/src/pages/Live.tsx frontend/src/router.tsx frontend/src/components/Layout.tsx frontend/src/pages/settings/MenuSettings.tsx docs/superpowers/specs/2026-10-09-live-trading-console-design.md docs/superpowers/plans/2026-10-09-live-trading-console.md
git commit -m "feat: add live trading console"
git push github main
```
