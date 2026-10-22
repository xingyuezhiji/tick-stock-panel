# Local Frontend 3011 Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the latest local frontend on port `3011` against the existing backend on port `3018` and verify the automatic-follow rule layout in a real browser.

**Architecture:** Vite serves the current frontend source on `127.0.0.1:3011` and proxies `/api` to the existing TSP backend on `127.0.0.1:3018`. Browser inspection confirms that the rendered rule card uses the new vertical layout and stays within its parent.

**Tech Stack:** Vite, React, Tailwind CSS, Playwright CLI

---

### Task 1: Start the Current Frontend

**Files:**
- Read: `frontend/vite.config.ts`
- Log: `frontend/.vite-3011.log`

- [ ] **Step 1: Confirm port 3011 is available**

Run:

```bash
lsof -nP -iTCP:3011 -sTCP:LISTEN
```

Expected: no listener. If a listener exists, terminate only that process.

- [ ] **Step 2: Start Vite with the existing backend proxy**

Run:

```bash
BACKEND_HOST=127.0.0.1 BACKEND_PORT=3018 \
  pnpm dev --host 127.0.0.1 --port 3011 > .vite-3011.log 2>&1
```

Expected: Vite listens on `http://127.0.0.1:3011`.

- [ ] **Step 3: Confirm the page and API are reachable**

Run:

```bash
curl -fsS http://127.0.0.1:3011/ >/dev/null
curl -fsS http://127.0.0.1:3011/api/paper/accounts >/dev/null
```

Expected: both commands exit successfully.

### Task 2: Verify the Rule Card in a Browser

**Files:**
- Inspect: `frontend/src/pages/Paper.tsx`
- Create: `output/playwright/paper-auto-rule-3011.png`

- [ ] **Step 1: Open the local frontend**

Run:

```bash
playwright-cli open http://127.0.0.1:3011/paper --headed
```

Expected: the paper-trading page loads using the existing account data.

- [ ] **Step 2: Inspect the rendered rule card**

Take a Playwright snapshot and verify the automatic-follow rule contains:

```text
title row: status, rule name, match kind, enable/disable, delete
second row: strategy ID
third row: direction, amount, order type, cooldown
```

Expected: all three rows are inside the automatic-follow card.

- [ ] **Step 3: Check horizontal overflow**

Read the card and page dimensions in the browser.

Expected:

```text
ruleCard.scrollWidth <= ruleCard.clientWidth
document.documentElement.scrollWidth <= document.documentElement.clientWidth
```

- [ ] **Step 4: Capture evidence**

Save a screenshot to:

```text
output/playwright/paper-auto-rule-3011.png
```

Expected: screenshot shows the latest vertical rule-card layout with no clipped controls.
