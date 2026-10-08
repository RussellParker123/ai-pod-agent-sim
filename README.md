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
  7. Marketing Agent
  8. Listing Agent
  9. Approval Gate
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

To optionally use read-only Etsy shop data, copy `.env.example` to `.env` and
provide `ETSY_SHOP_ID`, `ETSY_API_KEY`, `ETSY_API_SECRET`, and an Etsy OAuth
access token or refresh token with the `shops_r` scope. Etsy OAuth tokens must
be obtained through Etsy's OAuth authorization flow. Then run:

```bash
python -m app.sim.run_simulation --etsy-mode
```

Without valid Etsy credentials, the simulation uses its mock trend and
compliance behavior. Etsy API request logs are written to
`data/etsy_api.log`. Etsy's public API does not expose shop search-query
analytics or reasons for delisting, so trend terms are derived from active
listing tags and inactive listings are used only as similarity references.

Pricing research uses the median USD price of matching products in your own
active shop listings as a reference, when available. It is not competitor
research. Suggested prices are the higher of that reference and the price
needed for a 40% margin over the simulated product cost; this margin does not
include Etsy fees, shipping, taxes, or other expenses.

3. Run dashboard:

```bash
streamlit run app/dashboard.py
```

## Team review and publishing

Pipeline stages use configurable worker lists in `app/sim/team.py`. The default
team assigns two workers to prompt, image, compliance, mockup, and pricing
departments; stage work is distributed across those workers, and run JSON
records the assignments and manager ID. Pass an `AgentTeam` with custom worker
IDs to `run_once` to change the team.

To publish a saved run, use the Review page to explicitly approve GREENLIGHT
designs or force-approve HOLD designs. Compliance-blocked designs cannot be
approved. Then publish the reviewed run with a confirmation prompt:

```bash
python -m app.sim.run_simulation --publish-run run_YYYYMMDD_HHMMSS.json --real
```

Only explicitly approved designs are sent to the marketplace adapter. The
original run is preserved; publishing writes a separate `published_*.json`
result file.

## Marketing and search visibility

The marketing agent drafts product titles, descriptions, relevant keyword
phrases, Etsy tags (up to 13, each at most 20 characters), and image alt text
from each compliance-passed design's niche, product, and style metadata.
Review these drafts and the SEO action checklist on the Review page before
approving a design. Approved listings use the draft title, description, and
tags while preserving the AI-art disclosure. Runs without marketing metadata
retain the previous listing templates.

Recommendations cover accurate marketplace attributes, product photography,
and—only for a website you control—crawlability, sitemaps, Product structured
data, and Google Search Console measurement. Verify product facts and keyword
relevance before publishing. Alt text is a suggestion, not uploaded automatically.
These are rule-based drafts, not live keyword-volume research, and cannot
guarantee indexing or search rankings. Simulated views and sales do not measure
real SEO performance. The agent does not change approval decisions or publish
on its own. Custom teams may omit the `marketing` department to disable it.

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
