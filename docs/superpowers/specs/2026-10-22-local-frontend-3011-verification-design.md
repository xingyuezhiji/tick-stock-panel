# Local Frontend 3011 Verification Design

## Goal

Verify the latest `tick-stock-panel` frontend layout against the existing TSP
backend without changing or redeploying the service currently exposed on port
`3018`.

## Runtime Shape

- Start the Vite frontend from `frontend/` on `http://127.0.0.1:3011`.
- Keep the existing backend and data source on `http://127.0.0.1:3018`.
- Use the existing Vite proxy so `/api` requests from port `3011` reach port
  `3018`.
- Do not stop, replace, or modify the SSH-forwarded service on port `3018`.

## Verification

Open the paper-trading page through port `3011` and verify:

- the automatic-follow rule stays inside its card;
- the strategy name and ID truncate within the available width;
- rule details render below the title row;
- enable and delete controls stay inside the card;
- no horizontal page overflow appears at the desktop viewport.

Capture a browser screenshot after verification.

## Failure Handling

- If port `3011` is occupied, stop only the process listening on `3011`.
- If API requests fail, confirm the Vite proxy target is `3018`; do not alter
  backend data.
- If the latest layout still overflows on `3011`, inspect the rendered DOM and
  computed widths before making another layout change.
