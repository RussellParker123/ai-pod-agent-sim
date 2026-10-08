# AI POD Agent Simulation

Python multi-agent simulation for original AI-art print-on-demand workflows (mugs, t-shirts, etc.) with compliance checks and a human approval gate.

## What this project does
- Simulates a pipeline of agents:
  1. Trend Agent
  2. Prompt Agent
  3. Image Agent (simulated)
  4. Compliance Agent
  5. Mockup Agent
  6. Pricing Agent
  7. Listing Agent
  8. Approval Gate
- Produces synthetic marketplace outcomes (views, clicks, conversion, orders, revenue, profit).
- Visualizes results in a Streamlit dashboard.

## What this project does NOT do
- It does **not** copy Etsy designs.
- It does **not** auto-post live listings by default.

## Quickstart

1. Create virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\\Scripts\\activate   # Windows PowerShell
pip install -r requirements.txt
```

2. Run simulation from CLI:

```bash
python -m app.sim.run_simulation
```

3. Run dashboard:

```bash
streamlit run app/dashboard.py
```

## Project structure

- `app/sim/` core simulation modules and agent logic
- `app/dashboard.py` Streamlit visualization
- `app/setup/` setup wizards (Etsy config + OAuth connect)
- `app/integrations/` real API clients (Etsy, OpenAI, Printful)
- `app/live/` the real/live pipeline and order fulfillment sync
- `data/` generated run outputs (gitignored except structure)

## Notes
- All design assets are simulated metadata by default.
- Replace image/compliance/mockup stubs with real services via Live Mode below.

## Etsy-mode simulation (still simulated, no real API calls)

Run `python -m app.setup.etsy_wizard` to generate `data/etsy_config.json` with your
niches, product types, target margin, and Etsy's real fee structure (listing fee,
transaction fee %, payment processing fee). Then:

```bash
python -m app.sim.run_simulation --etsy-mode
```

This uses your config and deducts real Etsy fees from profit — still a fully
simulated run, no network calls.

## Live Mode — real Etsy shop, real AI art, real fulfillment

This repo can also run for real: generate real AI art, create draft listings on your
actual Etsy shop, mock them up on real Printful products, and auto-fulfill (print +
ship) paid orders. **Nothing goes public or spends money without an explicit human
approval step.**

### 1. Set up credentials

Copy `.env.example` to `.env` (gitignored, never commit it) and fill in:

- `ETSY_API_KEY` / `ETSY_SHARED_SECRET` — from your Etsy API app (developers.etsy.com)
- `ETSY_REDIRECT_URI` — must match the redirect URI registered on that app
- `OPENAI_API_KEY` — for real AI art generation (optional — falls back to simulated art if unset)
- `PRINTFUL_API_KEY` — for real printing + shipping (optional — required before any real order is placed)

### 2. Connect your Etsy shop (one-time OAuth)

```bash
python -m app.setup.etsy_wizard --connect-etsy
```

This prints an authorization URL. Open it, approve access, then copy the full
redirect URL your browser lands on and run:

```bash
python -m app.setup.etsy_wizard --complete-etsy-auth --redirect-url "<paste the full URL here>"
```

Tokens are stored locally in `.secrets/etsy_tokens.json` (gitignored).

### 3. Generate and review a live batch

Via the dashboard's **Live Ops** page, or on the CLI:

```bash
python -m app.live.pipeline run-batch --k 6   # creates Etsy DRAFT listings + Printful mockups
python -m app.live.pipeline list              # see what's pending approval
python -m app.live.pipeline approve <design_id>   # publishes that Etsy listing live
python -m app.live.pipeline reject <design_id>
```

Before going live, double-check the Etsy taxonomy ids and Printful variant ids in
`app/live/catalog_map.py` — the defaults are placeholders and must match your shop's
actual categories and chosen blank products.

### 4. Fulfill real orders

```bash
python -m app.live.order_sync
```

Polls your shop for new **paid** Etsy receipts and forwards each one to Printful as
an order (this is what makes Printful actually print and ship to the buyer). Each
receipt is only ever forwarded once.
