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
result file. Live publishing is unavailable from a fresh `run_once` execution;
Etsy failures stop the publish operation rather than being recorded as mock
listings.

## Project structure

- `app/sim/` core simulation modules and agent logic
- `app/dashboard.py` Streamlit visualization
- `data/` generated run outputs

## Notes
- All design assets are simulated metadata in this starter.
- Replace image/compliance/mockup stubs with real services later.
