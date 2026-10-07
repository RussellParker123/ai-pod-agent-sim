# AI POD Agent Simulation

Python multi-agent simulation for original AI-art print-on-demand workflows (mugs, t-shirts, etc.) with compliance checks and a human approval gate.

## What this project does
- Simulates a pipeline of agents:
  1. Trend Agent
  2. Market Research Agent
  3. Design Agent
  4. Prompt Agent
  5. Image Agent (simulated)
  6. Compliance Agent
  7. Mockup Agent
  8. Sweater & Hoodie Agent
  9. Pricing Agent
  10. Approval Gate
  11. Market Simulator
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
Market research reports active-tag signals from the connected shop only; it
does not represent marketplace-wide search demand or competitor analysis.
Without Etsy data, those signals are simulated. The apparel specialist routes
the strongest concepts to sweaters and hoodies and uses estimated product costs.

3. Run dashboard:

```bash
streamlit run app/dashboard.py
```

## Project structure

- `app/sim/` core simulation modules and agent logic
- `app/dashboard.py` Streamlit visualization
- `data/` generated run outputs

## Notes
- All design assets are simulated metadata in this starter.
- Replace image/compliance/mockup stubs with real services later.
