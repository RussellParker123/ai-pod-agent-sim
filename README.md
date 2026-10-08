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
- `data/` generated run outputs

## Notes
- All design assets are simulated metadata in this starter.
- Replace image/compliance/mockup stubs with real services later.
