"""Real GPT-backed reasoning agents for live mode: a Trend Research agent
and a Prompt Writer agent that call OpenAI chat completions, working
alongside the exact same Design objects and downstream agents
(compliance_agent, mockup_agent, pricing_agent, ManagerAgent) used by the
simulation.

Both fall back to the simulation's lightweight random/template logic
(app.sim.agents.trend_agent / prompt_agent) when OPENAI_API_KEY isn't set,
so the live pipeline keeps working without it.
"""
from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from app.integrations import openai_text
from app.integrations.config import DATA_DIR
from app.sim.agents import Design, prompt_agent, trend_agent

TREND_SYSTEM_PROMPT = (
    "You are the Trend Research Agent for a solo print-on-demand Etsy shop. Given a list of "
    "candidate niches, propose specific, concrete design concepts (4-8 words each, e.g. "
    "'sleepy cat drinking coffee') within those niches that would sell well on Etsy right now. "
    "Spread concepts across all the given niches. For each concept, assign a trend_score between "
    "0.45 and 0.98 reflecting how hot you believe it is. "
    'Return ONLY valid JSON of this shape: {"designs": [{"niche": "<one of the given niches>", '
    '"concept": "<short concept phrase>", "trend_score": <float>}, ...]}'
)

PROMPT_SYSTEM_PROMPT = (
    "You are the Prompt Agent for a solo print-on-demand Etsy shop. Given a niche and a short "
    "design concept, write ONE original art-generation prompt (1-2 sentences) for an AI image "
    "generator to illustrate it. Rules: no logos, no brand names, no copyrighted characters, no "
    "trademarked phrases, must read as clearly commercial-safe and sellable, vector/illustration "
    "style by default unless the concept suggests otherwise. "
    'Return ONLY valid JSON of this shape: {"prompt": "<the prompt text>"}'
)

_DESIGN_ID_SEQ_PATH = DATA_DIR / "design_id_seq.json"


def _next_design_ids(n: int) -> List[str]:
    """Allocates n globally-unique design IDs, persisted across runs/batches
    (data/design_id_seq.json). Every live batch used to start back at D001,
    so two batches could mint the exact same design_id (e.g. 'D010-v1') —
    that collided in pending_approvals.json and crashed the Live Ops page
    with a duplicate Streamlit widget key. This guarantees every ID handed
    out is unique forever, not just within one batch."""
    last = 0
    if _DESIGN_ID_SEQ_PATH.exists():
        with open(_DESIGN_ID_SEQ_PATH, "r", encoding="utf-8") as f:
            last = json.load(f).get("last", 0)
    ids = [f"D{last + i + 1:04}" for i in range(n)]
    _DESIGN_ID_SEQ_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_DESIGN_ID_SEQ_PATH, "w", encoding="utf-8") as f:
        json.dump({"last": last + n}, f)
    return ids


def trend_agent_live(niches: List[str], k: int = 24) -> List[Design]:
    """GPT-backed trend research: asks OpenAI to propose k concrete design
    concepts spread across the given niches, each with a trend_score.
    Falls back to the simulation's random trend_agent() if OPENAI_API_KEY
    isn't set. The proposed concept text is stashed in Design.prompt as a
    seed for prompt_agent_live() to expand into a full art prompt."""
    if not openai_text.is_configured():
        designs = trend_agent(niches=niches, k=k)
        for d, new_id in zip(designs, _next_design_ids(len(designs))):
            d.design_id = new_id
        return designs

    try:
        data = openai_text.chat_json(
            TREND_SYSTEM_PROMPT,
            f"Candidate niches: {', '.join(niches)}. Propose {k} design concepts total, "
            f"spread across these niches.",
        )
        items = data.get("designs", [])[:k]
        if not items:
            raise ValueError("GPT returned no design concepts")
        ids = _next_design_ids(len(items))
        out = []
        for new_id, item in zip(ids, items):
            niche = item.get("niche") if item.get("niche") in niches else random.choice(niches)
            try:
                score = float(item.get("trend_score", 0.6))
            except (TypeError, ValueError):
                score = 0.6
            out.append(
                Design(
                    design_id=new_id,
                    niche=niche,
                    trend_score=round(max(0.0, min(1.0, score)), 3),
                    prompt=str(item.get("concept", "")),
                )
            )
        return out
    except Exception:
        # Any API/parse hiccup: don't block the whole pipeline, fall back.
        designs = trend_agent(niches=niches, k=k)
        for d, new_id in zip(designs, _next_design_ids(len(designs))):
            d.design_id = new_id
        return designs


def _write_one_prompt(d: Design) -> None:
    seed = d.prompt or d.niche
    data = openai_text.chat_json(PROMPT_SYSTEM_PROMPT, f"Niche: {d.niche}. Design concept: {seed}.")
    prompt = data.get("prompt")
    if not prompt:
        raise ValueError("GPT returned an empty prompt")
    d.prompt = str(prompt)


def prompt_agent_live(designs: List[Design], max_workers: int = 4) -> None:
    """GPT-backed prompt writing: expands each design's trend concept (or
    niche, if generated by the simulation's trend_agent) into a full,
    original, trademark-safe art prompt, in parallel. Falls back per-design
    to the simulation's static template on any API error, so one bad call
    doesn't block the whole batch."""
    if not openai_text.is_configured() or not designs:
        prompt_agent(designs)
        return

    with ThreadPoolExecutor(max_workers=min(max_workers, len(designs))) as pool:
        futures = {pool.submit(_write_one_prompt, d): d for d in designs}
        for future in as_completed(futures):
            d = futures[future]
            try:
                future.result()
            except Exception:
                prompt_agent([d])  # fall back to the static template for just this one
