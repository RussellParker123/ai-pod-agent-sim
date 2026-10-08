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
python -m app.sim.run_simulation                       # 24 candidates
python -m app.sim.run_simulation --batch-size 12 --seed 7   # smaller, reproducible
```

Each run is saved as a new `data/run_<timestamp>.json` (a `_2`, `_3`, ...
suffix is added if two runs start in the same second); older runs are never
overwritten.

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
needed for the configured target margin (42% by default) over the product cost; this margin does not
include Etsy fees, shipping, taxes, or other expenses.

3. Run dashboard (the entrypoint is `app/dashboard.py`; extra pages live in `app/pages/`):

```bash
streamlit run app/dashboard.py
```

You do not need to run step 2 first. On a fresh checkout with no runs the
dashboard shows **Start an offline simulation**: choose the number of
candidates (and optionally a fixed seed) and press **Run offline simulation**.
Once runs exist the same form is in the sidebar. The form calls the existing
simulator (`run_once`) only when you press the button - never on page
reruns - and only in offline mode: no API calls, no paid image generation, no
publishing. The new run is selected automatically; failures are shown as an
error and no partial run is selected.

**Updating a running older checkout.** Streamlit does not reliably reload
changed modules (e.g. `app/arena.py`) in a server that is already running, so
after updating:

```bash
git pull                      # or check out the branch/commit you want
pip install -r requirements.txt
# stop the running server (Ctrl+C in its terminal), then
streamlit run app/dashboard.py
```

and hard-refresh the browser tab (Ctrl+Shift+R). If the header reads
"RECORDED-RUN REPLAY" and the agent cards include a **RECYCLER** card, you are
on the updated version. The repository cannot tell which version a hosted
deployment is running; redeploy it from the updated commit.

## Team review and publishing

Pipeline stages use configurable worker lists in `app/sim/team.py`. The default
team assigns two workers to prompt, image, compliance, mockup, and pricing
departments, one to marketing and one recycler to the Recycling Facility; stage
work is distributed across those workers, and run JSON records the assignments,
each agent's home/current department, transfer events and the manager ID. Pass
an `AgentTeam` with custom worker IDs to `run_once` to change the team (a custom
team is used as-is; otherwise the saved roster in `data/team_state.json` is used).

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

## Art quality: briefs, checks and reviewer feedback

The Prompt Agent no longer fills a generic niche template. For every design it
builds a structured, product-aware creative brief (`app/sim/art_quality.py`):
niche and concept, one concrete focal motif, the best-fitting target product
(from the product-fit table and research), composition, style and palette,
legibility limits (max words of on-product text), the product's print area and
background constraints, originality guardrails (no logos, brands, existing
characters or trademarked phrases) and any reviewer feedback recorded so far.
Research signals (top styles/products/niches) feed the brief, and the prompt is
rendered from it. In Live Mode, GPT receives the same brief as JSON; any API
failure falls back to the deterministic template for that design.

Quality is checked in two separate, clearly labelled steps:

- **Concept pre-check (before any image).** Text-only, explainable checks on the
  brief/prompt: protected names, originality guardrails, product fit, specificity,
  legibility, print constraints and palette. Each check records a reason and a
  concrete fix. Fixable issues trigger a bounded rework (at most 2 rounds, and it
  stops if the prompt would not change). A protected name in the niche itself is a
  blocker the Manager will BLOCK. This is *concept* approval: it does not look at
  pixels and does not establish visual quality or legal safety.
- **Generated-image assessment (after an image exists).** Offline it only checks
  the file (exists, PNG header, size); simulated images are reported as having no
  pixels. An optional `image_assessor(path, brief)` callable can be passed to
  `run_live_batch_stream`; if it is missing or fails, the result says so. Images
  are never regenerated automatically and no extra paid images are created.

Compliance flags stay blocking. A flagged design is re-checked only if it was
actually reworked from the compliance notes (once per design); unchanged
designs are rejected instead of being re-rolled. Every revision, compliance
rework and manager coaching note is stored in `review_history` and shown on the
Review page with the brief and checks, so you can audit what changed and why.
Approval thresholds were not changed: in a 30-seed offline comparison the
simulated greenlight rate stayed the same while average product fit rose
(0.80 → 0.91) because briefs target the best-fitting product.

## Dr. Cypher (manager character)

Dr. Cypher is the Manager agent as a persistent character (`app/sim/characters.py`,
stable id `dr-cypher`, avatar from `app/utils/dr_cipher.py` — internal names keep
the older "cipher" spelling). Each run records where he went (trend, compliance,
pricing, approval, recycling), what he did there, the counts behind it and his
mood, which follows the batch result. It is saved in the run's
`manager.character`; older runs rebuild it from their recorded decisions. The
dashboard, Office page and arena show his location, mood and original dialogue
(all text is HTML-escaped).

## Agents moving between departments

Every worker has a stable `agent_id`, a home department and a current
department. Transfers (`AgentTeam.transfer`) are validated: unknown agents or
departments, moves outside the agent's skill group (creative: prompt/image ·
review: compliance/recycling · commerce: mockup/pricing/marketing), agents in
the middle of a task, and moves that would leave a department empty are
rejected. Worker IDs must be unique across departments. A transfer changes who
`run_stage` assigns work to from then on, and every move is recorded as an event.

- **Manual control:** the Office page has a transfer form and a "return everyone
  home" button. Moves are saved to `data/team_state.json` and apply to the next
  simulation run.
- **Automatic, demand-based:** when the Recycling Facility has more work than its
  staff can handle (more than 4 items per worker), an idle, cross-trained agent is
  temporarily borrowed and returned home at the end of the run.

## Recycling Facility

Rejected art that **already has an image** goes to the Recycling Facility
(`app/sim/recycling.py`, queue in `data/recycling_queue.json`) instead of
disappearing:

- simulation designs the Manager BLOCKs (including compliance-flagged ones),
- designs you cancel on the Review page,
- live designs you reject in Live Ops (with your reason) or via
  `python -m app.live.pipeline reject <design_id> --reason "..."`,
- Image Archive files you mark "Hold for reuse" (orphans without metadata go to
  quarantine for manual review).

Concept-only rejections (no image yet) are listed as skipped and never trigger
image generation. Each record keeps the original image path/URI (the file is
never deleted or modified), source design ID, niche, product, prompt, brief,
rejection reason, compliance status and provenance. Records are deduplicated,
so repeated runs or button clicks do not create duplicates.

The recycler agent cross-references **metadata only** — the product-fit table,
research, approved designs and the image manifest — and suggests an alternate
product, alternate niche, a crop/rework (real images only) or archive/no-use,
each with confidence, reasons and reference IDs (e.g.
`product_fit:bookish humor:tote`, `approved_design:A7`). It does not inspect
pixels, so a human must look at the image. Compliance-flagged, protected-name or
concept-blocked assets are quarantined and can never be requested for reuse;
quarantined/unusable images are also refused by "Stage as Etsy draft" in the archive.

Reuse is always explicit and gated: on the Recycling page you choose a
suggestion → a **new** candidate design (`<source>-R1-<id>`) reuses the
existing image, starts unapproved with compliance pending, and goes back
through current compliance, concept checks, pricing and Manager scoring. The
next simulation run includes it, and it then needs your approval on the Review
page; recycled candidates are never auto-listed. Live candidates become an Etsy
**draft** queued for your approval in Live Ops and are never auto-published.
The original rejected record is never changed to approved. Analysis is capped at
3 attempts and a recycled candidate that is rejected again is not recycled a
second time.

## Arena and Office views

The dashboard arena is a **replay** of the selected recorded run, not live
backend work: every outcome (approved, held, blocked, rejected, recycled) and
every worker assignment comes from the run file, but the timing and walking
are animation. Live Mode work is never shown as a replay and the replay never
calls any API.

- **Agents working together.** Each worker has its recorded ID. Designs are
  given to the worker the run actually assigned them to (round-robin per
  department, reconstructed from `team.assignments`; if the recorded counts
  don't match, any worker in that room takes it). Workers carry each design
  to the next department on its real path, so you see handoffs, the current
  task/design ID, a progress ring and a handoff log. Departments work in
  parallel. A room with no worker in a custom team gets a labelled placeholder
  instead of a stuck queue. Recorded transfers are replayed in order, e.g.
  a worker loaned to recycling on demand and returning at end of shift.
- **Resolution.** Every design ends as completed, held, blocked, rejected,
  pending reuse, quarantined or unusable. The ops board counts each one and the
  replay only finishes when all are resolved (also for reject-all and empty runs).
- **Dr. Cypher** walks from the command center to each department he actually
  reviewed and speaks his recorded line. Visits to departments that no design
  reached (e.g. pricing in a reject-all run) are **skipped with an explanation**
  instead of waiting forever. Between visits he patrols busy rooms; those checks
  are labelled "replay check, not a recorded decision". When all work is
  resolved he returns to the command center. For older runs without a recorded
  character his visits are reconstructed from the manager decision log and
  labelled as such; with no manager report there are no recorded visits.
- **Recycler and reuse plans.** Rejected designs that already have an image
  (never concept-only rejections) are carried to the Recycling Facility, where
  the recycler reviews them. Click the **Recycling Facility** or the
  **recycler** to see, per image: source image, why it was rejected, review
  status, the recycler's proposed plan (alternate product/niche, rework or
  archive/quarantine) with confidence, reasons and references, and provenance.
  Plans come only from the recorded analysis (the recycling queue entry for
  this run, else the run's snapshot); otherwise the facility says **Not
  analyzed yet**. Analysis is metadata cross-referencing - image pixels are not
  inspected, and `sim://` assets have no pixels at all. Queue records from other
  runs are counted separately and never attributed to the selected run. The
  **RECYCLER** agent card summarises "x/y unused images planned", and the link
  under the arena opens the **Recycling** page for previews, re-analysis,
  manual reuse requests and quarantine. Reuse still requires fresh quality and
  compliance gates plus explicit human approval; nothing is auto-published.

The Office page shows the roster per department, Dr. Cypher's profile and
visits, the run's movement events and the transfer controls.

Limitations: the replay's timing is synthetic (runs record outcomes and
assignments, not a per-event timeline); stage assignments for runs recorded
before `team.assignments` existed fall back to whichever worker is free.

## Project structure

- `app/sim/` core simulation modules and agent logic
- `app/sim/art_quality.py` creative briefs, concept pre-check, refinement, image assessment
- `app/sim/characters.py` Dr. Cypher character state
- `app/sim/recycling.py` Recycling Facility queue and recycler cross-reference
- `app/dashboard.py` Streamlit visualization; `app/pages/` Manager, Review, Office, Live Ops, Recycling
- `app/setup/` setup wizards (Etsy config + OAuth connect)
- `app/integrations/` real API clients (Etsy, OpenAI, Printful)
- `app/live/` the real/live pipeline and order fulfillment sync
- `data/` generated run outputs (gitignored except structure)

## Tests

```bash
pip install pytest playwright
playwright install chromium   # optional; a system chromium/chrome is used as fallback
python -m pytest -q
```

`tests/test_arena_browser.py` runs the arena JavaScript in headless Chromium
(animation progress, handoffs, transfers, recycler plans, Dr. Cypher's visits
and return, escaping, no console errors) and is skipped when Playwright or a
browser is unavailable. `tests/test_offline_launch.py` drives the dashboard with
Streamlit's AppTest using a temporary data directory and blocks network access.

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
python -m app.live.pipeline reject <design_id> --reason "why"   # image goes to the Recycling Facility
```

Live batches keep the spend safeguards: the Manager greenlights *concepts* before
any image is generated, so rejected concepts cost nothing and are not recycled. Each
greenlit design (or art-team variant) gets at most one paid image, with no automatic
regeneration. Manager auto-publish is off by default. Recycled reuse candidates
never generate new images and are never auto-published.

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
