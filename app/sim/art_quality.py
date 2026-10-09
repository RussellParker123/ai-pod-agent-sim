"""Structured creative briefs, explainable quality checks and bounded refinement.

Art creators work from a product-aware brief (concept, composition, palette,
legibility, print constraints, originality guardrails and reviewer feedback)
instead of a one-line niche template. Every check here is explainable and
deterministic.

Limitations (stated honestly, also surfaced in the UI):
- ``assess_concept`` is a *pre-generation*, text/metadata-only check. It cannot
  judge how an image will look, whether it resembles existing work, or whether
  it is legally safe. Passing it is not visual or IP clearance.
- ``assess_generated_image`` only inspects pixels if an optional image
  assessor callable is supplied. Without one it performs offline file checks
  (exists, PNG header, resolution) and reports ``image_inspected: False``.
- Nothing in this module generates or regenerates images, so it never spends
  money on its own.
"""
from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from app.sim.manager import PRODUCT_FIT

BRIEF_VERSION = 1
MAX_REFINEMENT_ROUNDS = 2
MAX_COMPLIANCE_REWORKS = 1
DEFAULT_PRODUCTS = ("mug", "tshirt", "tote")

PRINT_SPECS = {
    "mug": {
        "print_area": "8.5 x 3.5 in wrap; make a continuous left-to-right scene, keeping its key subject in the central 3.5 x 3.5 in safe area",
        "min_resolution": "2475 x 1155 px at 300 DPI",
        "background": "transparent or solid white (white glossy mug)",
        "max_words": 4,
    },
    "tshirt": {
        "print_area": "12 x 16 in chest print, centered emblem, no full-bleed rectangle",
        "min_resolution": "3600 x 4800 px at 300 DPI",
        "background": "transparent; add a thin outline so it holds on light shirts",
        "max_words": 6,
    },
    "tote": {
        "print_area": "10 x 10 in centered",
        "min_resolution": "3000 x 3000 px at 300 DPI",
        "background": "transparent; light ink only (black tote)",
        "max_words": 5,
    },
}
DEFAULT_SPEC = {
    "print_area": "centered artwork with a 10% safety margin",
    "min_resolution": "3000 x 3000 px at 300 DPI",
    "background": "transparent",
    "max_words": 5,
}

PRODUCT_PALETTE_NOTES = {
    "mug": "dark anchor color for contrast on white ceramic",
    "tshirt": "limited 3-4 spot colors that read on light fabric",
    "tote": "light, high-value colors (cream, pale yellow, white) that read on black canvas",
}

NICHE_MOTIFS = {
    "coffee culture": [
        "steaming pour-over kettle with rising swirl",
        "latte-art heart cup seen from above",
        "coffee bean constellation around a tiny moon",
    ],
    "bookish humor": [
        "towering stack of books with a sleepy reading lamp",
        "bookworm wearing round glasses peeking from a book",
        "open book turning into a cozy armchair",
    ],
    "minimalist motivation": [
        "single upward line becoming a mountain peak",
        "small sprout growing from a geometric block",
        "rising sun made of three simple arcs",
    ],
    "retro outdoors": [
        "sunset over layered pine-covered mountains",
        "vintage camper van under a starry sky",
        "canoe on a calm lake with sun rays",
    ],
    "pet lovers": [
        "curled-up sleeping cat with a tiny heart",
        "happy dog peeking over a paw-print badge",
        "cat and dog sharing a blanket",
    ],
    "cozy autumn": [
        "winding woodland trail beneath golden and russet autumn trees",
        "storybook fox beside a pumpkin lantern among fallen leaves",
        "friendly little ghosts drifting through a moonlit pine forest",
        "knitted sweater with a small pumpkin and falling-leaf pattern",
        "mushroom cottage tucked beneath amber leaves and tiny glowing windows",
        "quiet harvest orchard with pumpkins, curling vines, and distant hills",
        "tiny deer standing by a leaf-covered path at golden hour",
    ],
    "western desert": [
        "golden-hour trail winding through red-rock mesas and cottonwood trees",
        "prickly pear cactus in bloom among desert marigolds and silver sage",
        "pair of well-worn cowboy boots with prairie wildflowers curling around them",
        "quiet canyon camp with a glowing lantern, distant horse, and starry sky",
        "small desert river beneath layered mesas and a flock of migrating birds",
        "ranch hat resting beside a sprig of bluebonnets and golden grasses",
        "horseshoe entwined with sagebrush and tiny desert blossoms",
    ],
}
GENERIC_MOTIFS = [
    "badge-style emblem with one simple central icon",
    "single bold silhouette with a circular backdrop",
    "playful hand-drawn icon cluster around one focal object",
]

STYLE_DIRECTIONS = [
    "bold flat-color vector",
    "retro screen-print with three spot colors",
    "single-weight line art",
    "geometric badge illustration",
    "hand-painted watercolor with soft layered washes",
    "warm folk-art gouache illustration",
]

PALETTES = {
    "cozy": "warm cream, amber, rust, soft moss green, dark evergreen",
    "autumn": "maple gold, rust, muted moss green, warm cream, dark bark brown",
    "retro": "faded teal, sunset orange, mustard, dark navy",
    "vintage": "faded teal, sunset orange, mustard, dark navy",
    "minimalist": "near-black, off-white, one coral accent",
    "boho": "terracotta, sage, sand, charcoal",
    "watercolor": "soft sage, blush, slate blue, charcoal outline",
    "coffee": "espresso brown, latte tan, cream, black",
    "pet": "warm ginger, soft gray, cream, charcoal",
    "western": "terracotta, rust, golden ochre, muted sage, turquoise accent, warm cream, dark umber",
    "southwestern": "terracotta, rust, golden ochre, muted sage, turquoise accent, warm cream, dark umber",
}
DEFAULT_PALETTE = "3-4 flat colors with one dark anchor color"

ORIGINALITY_GUARDRAILS = [
    "original artwork only",
    "use market trends only as high-level inspiration; do not reproduce existing artwork, wording or composition",
    "no logos, brand names or trademarked phrases",
    "no existing characters, celebrities or franchise references",
    "do not imitate a named living artist",
]

# Brand / franchise names that must never appear in a concept. This is a
# small illustrative list, NOT a trademark search.
RISKY_TERMS = [
    "disney", "marvel", "pixar", "pokemon", "nintendo", "star wars", "harry potter",
    "hogwarts", "nike", "adidas", "starbucks", "coca cola", "nfl", "nba", "taylor swift",
    "barbie", "hello kitty", "lego", "batman", "spiderman", "spider-man", "mickey", "snoopy",
    "stranger things", "minecraft", "fortnite",
]
_RISKY_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in RISKY_TERMS) + r")\b", re.IGNORECASE)
_QUOTED_RE = re.compile(r"[\"\u201c]([^\"\u201d]{1,200})[\"\u201d]")

CONCEPT_LIMITATIONS = (
    "Pre-generation text/metadata check only: it cannot judge visual quality, resemblance "
    "to existing work, or legal/IP safety of the eventual image."
)
IMAGE_LIMITATIONS = (
    "Pixels are only inspected when an image assessor is configured. Offline checks cover "
    "file presence, PNG header and resolution; they are not a visual-quality or IP review."
)


def _stable_index(key: str, n: int) -> int:
    if n <= 0:
        return 0
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % n


def risky_terms_in(text: str) -> List[str]:
    return sorted({m.group(1).lower() for m in _RISKY_RE.finditer(text or "")})


def strip_risky_terms(text: str) -> str:
    cleaned = _RISKY_RE.sub("", text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip(" ,-")


def _feedback_from_history(history: Iterable[Dict]) -> List[str]:
    out: List[str] = []
    for entry in history or []:
        for item in entry.get("feedback", []) or []:
            if item and item not in out:
                out.append(str(item))
    return out


def best_product_for(niche: str, product_types: Iterable[str], research: Optional[Dict] = None) -> str:
    allowed = [p for p in (product_types or DEFAULT_PRODUCTS)]
    if not allowed:
        return ""
    top_products = list((research or {}).get("top_product_types", []) or [])
    fits = PRODUCT_FIT.get(niche, {})

    def rank(p):
        return (fits.get(p, 0.6) + (0.05 if p in top_products else 0.0), -allowed.index(p))

    return max(allowed, key=rank)


def _initial_concept(design) -> str:
    brief = design.brief or {}
    if brief.get("concept"):
        return str(brief["concept"])
    seed = (design.prompt or "").strip()
    # Live trend research stashes a short concept phrase in prompt.
    if seed and len(seed.split()) <= 12:
        return seed
    return design.niche


def build_brief(
    design,
    research: Optional[Dict] = None,
    product_types: Optional[Iterable[str]] = None,
    rework: bool = False,
) -> Dict:
    """Return a structured creative brief for ``design``.

    ``rework=True`` applies fixes derived from recorded reviewer feedback:
    risky terms are stripped, overlong slogans are shortened, and the
    style/motif shift to a new direction when a similarity issue was raised.
    """
    previous = design.brief or {}
    product_types = tuple(product_types or previous.get("allowed_products") or DEFAULT_PRODUCTS)
    concept = _initial_concept(design)
    variation = int(previous.get("variation", 0))
    target = previous.get("target_product") if previous.get("target_product") in product_types else ""
    if not target or rework:
        target = best_product_for(design.niche, product_types, research)
    spec = PRINT_SPECS.get(target, DEFAULT_SPEC)

    avoid = list(previous.get("avoid", []))
    if rework:
        concept = strip_risky_terms(concept) or design.niche
        quoted = _QUOTED_RE.findall(concept)
        for phrase in quoted:
            words = phrase.split()
            if len(words) > spec["max_words"]:
                concept = concept.replace(phrase, " ".join(words[: spec["max_words"]]))

    generic = concept.strip().lower() == design.niche.strip().lower() or len(concept.split()) < 3
    motifs = NICHE_MOTIFS.get(design.niche, GENERIC_MOTIFS)
    if generic:
        idx = (_stable_index(design.design_id + design.niche, len(motifs)) + variation) % len(motifs)
        motif = motifs[idx]
    else:
        motif = concept

    keywords = [k for k in (design.style_keywords or []) if k and k != "minimal"]
    research_styles = list((research or {}).get("top_styles", []) or [])
    style_seed = (keywords or research_styles or [""])[0]
    style = STYLE_DIRECTIONS[(_stable_index(design.niche, len(STYLE_DIRECTIONS)) + variation) % len(STYLE_DIRECTIONS)]
    if style_seed:
        style = f"{style_seed} {style}"

    palette = DEFAULT_PALETTE
    palette_key = " ".join([design.niche, style]).lower()
    for key, value in PALETTES.items():
        if key in palette_key:
            palette = value
            break
    palette = f"{palette}; {PRODUCT_PALETTE_NOTES.get(target, 'high contrast')}"

    research_signals = {}
    if research:
        research_signals = {
            "source": research.get("source", "unknown"),
            "niche_weight": (research.get("top_niches") or {}).get(design.niche),
            "top_styles": research_styles,
            "top_product_types": list(research.get("top_product_types", []) or []),
        }

    return {
        "version": BRIEF_VERSION,
        "niche": design.niche,
        "concept": concept,
        "motif": motif,
        "target_product": target,
        "allowed_products": list(product_types),
        "composition": (
            "continuous panoramic wrap scene with a clear focal subject in the central safe area, "
            "supporting details flowing toward the sides, and no essential detail at the seam"
            if target == "mug" else
            "one focal subject, centered, generous margin, readable at thumbnail size"
        ),
        "art_direction": (
            "Create polished, handcrafted giftable artwork rather than generic clip art. When the "
            "theme suits it, use a cozy storybook mood with layered watercolor or gouache texture, "
            "warm natural color harmony, and a few charming secondary details; adapt the finish to "
            "the selected style and palette. For Western desert themes, use layered red-rock "
            "landforms, golden-hour light, and restrained sage or wildflower accents for a warm "
            "illustrated keepsake feel. For a mug wrap, build a coherent left-to-right scene with "
            "a strong central focal point and lighter supporting detail toward the edges. Keep a "
            "clear focal hierarchy, distinctive silhouette, deliberate negative space, and "
            "print-safe detail. Make standalone printable artwork, not a product photo or mockup, "
            "and never reproduce a reference's "
            "specific characters, wording, or composition."
        ),
        "style": style,
        "palette": palette,
        "legibility": {
            "max_words": spec["max_words"],
            "rule": f"text optional; at most {spec['max_words']} words, heavy sans-serif, no thin script",
        },
        "print_constraints": dict(spec),
        "originality": list(ORIGINALITY_GUARDRAILS),
        "avoid": avoid,
        "reviewer_feedback": _feedback_from_history(design.review_history),
        "research_signals": research_signals,
        "variation": variation,
        "compliance_reworks": int(previous.get("compliance_reworks", 0)),
        "revision": int(previous.get("revision", -1)) + 1,
    }


def render_prompt(brief: Dict) -> str:
    spec = brief.get("print_constraints", DEFAULT_SPEC)
    product = brief.get("target_product") or "print product"
    parts = [
        f"Original {brief.get('style', 'vector')} illustration for a {product} print: "
        f"{brief.get('motif') or brief.get('concept')} ({brief.get('niche')} theme).",
        f"Composition: {brief.get('composition')}.",
        f"Art direction: {brief.get('art_direction', 'clear visual hierarchy, crisp silhouette, intentional detail and negative space')}.",
        f"Palette: {brief.get('palette')}.",
        f"Legibility: {brief.get('legibility', {}).get('rule')}.",
        f"Print: {spec.get('print_area')}; background {spec.get('background')}.",
        "Guardrails: " + "; ".join(brief.get("originality", ORIGINALITY_GUARDRAILS)) + ".",
    ]
    if brief.get("avoid"):
        parts.append("Avoid: " + "; ".join(brief["avoid"]) + ".")
    if brief.get("reviewer_feedback"):
        parts.append("Reviewer feedback to apply: " + " ".join(brief["reviewer_feedback"][-3:]))
    return " ".join(parts)


def _check(name, passed, reason, fix="", blocker=False):
    return {"name": name, "passed": bool(passed), "reason": reason, "fix": fix,
            "fixable": (not passed) and not blocker, "blocker": (not passed) and blocker}


def assess_concept(design) -> Dict:
    """Explainable pre-generation checks on the brief + prompt text."""
    brief = design.brief or {}
    prompt = design.prompt or ""
    lowered = prompt.lower()
    target = brief.get("target_product") or design.product_type
    spec = PRINT_SPECS.get(target, DEFAULT_SPEC)
    checks = []

    niche_terms = risky_terms_in(design.niche)
    concept_terms = risky_terms_in(" ".join([brief.get("concept", ""), brief.get("motif", ""), prompt]))
    if niche_terms:
        checks.append(_check(
            "protected_terms", False,
            f"niche itself references protected names: {', '.join(niche_terms)}",
            blocker=True,
        ))
    else:
        checks.append(_check(
            "protected_terms", not concept_terms,
            "no brand/franchise names found in concept or prompt" if not concept_terms
            else f"concept/prompt mentions protected names: {', '.join(concept_terms)}",
            fix="Remove brand/franchise names; describe the subject generically.",
        ))

    has_guardrails = "no logos" in lowered and ("no existing characters" in lowered or "no characters" in lowered)
    checks.append(_check(
        "originality_guardrails", has_guardrails,
        "prompt carries originality guardrails" if has_guardrails else "prompt lacks no-logo/no-character guardrails",
        fix="Re-render the prompt from the brief so originality guardrails are included.",
    ))

    fits = PRODUCT_FIT.get(design.niche, {})
    allowed = brief.get("allowed_products") or list(DEFAULT_PRODUCTS)
    best = best_product_for(design.niche, allowed)
    fit = fits.get(target)
    fit_ok = fit is None or fit >= 0.7 or fits.get(best, 0) <= fit
    checks.append(_check(
        "product_fit", fit_ok,
        f"{target or 'product'} fit for '{design.niche}' is {fit if fit is not None else 'unknown (no reference)'}",
        fix=f"Retarget the brief to {best} (fit {fits.get(best)}).",
    ))

    generic = (brief.get("motif") or "").strip().lower() in ("", design.niche.strip().lower())
    checks.append(_check(
        "specificity", not generic,
        "concrete focal motif defined" if not generic else "concept is just the niche name (generic art sells poorly)",
        fix="Pick one concrete focal motif for the niche.",
    ))

    too_long = [p for p in _QUOTED_RE.findall(" ".join([brief.get("concept", ""), prompt]))
                if len(p.split()) > spec["max_words"]]
    checks.append(_check(
        "legibility", not too_long,
        "any text fits the product's word limit" if not too_long
        else f"slogan longer than {spec['max_words']} words will not read at print size",
        fix=f"Shorten on-product text to {spec['max_words']} words or fewer.",
    ))

    print_ok = bool(brief.get("print_constraints")) and "print:" in lowered
    checks.append(_check(
        "print_constraints", print_ok,
        "prompt states print area and background" if print_ok else "prompt does not state print area/background",
        fix="Include the product print area and background requirements.",
    ))

    palette_ok = bool(brief.get("palette"))
    checks.append(_check(
        "palette", palette_ok,
        "product-aware palette defined" if palette_ok else "no palette defined",
        fix="Define a limited, product-aware palette.",
    ))

    blockers = [c for c in checks if c["blocker"]]
    fixable = [c for c in checks if c["fixable"]]
    status = "blocked" if blockers else ("needs_revision" if fixable else "pass")
    return {
        "kind": "concept_precheck",
        "status": status,
        "score": round(sum(c["passed"] for c in checks) / len(checks), 3),
        "checks": checks,
        "issues": [c["reason"] for c in checks if not c["passed"]],
        "feedback": [c["fix"] for c in fixable],
        "image_inspected": False,
        "limitations": CONCEPT_LIMITATIONS,
    }


def _record(design, entry: Dict) -> None:
    design.review_history.append(entry)


def refine_designs(
    designs: List,
    research: Optional[Dict] = None,
    product_types: Optional[Iterable[str]] = None,
    max_rounds: int = MAX_REFINEMENT_ROUNDS,
) -> Dict:
    """Run the concept pre-check and rework fixable issues, at most
    ``max_rounds`` times per design. Designs whose prompt cannot change are
    not re-checked. Returns a summary of what happened."""
    summary = {"checked": 0, "revised": 0, "passed": 0, "blocked": 0, "needs_revision": 0}
    for d in designs:
        if d.lineage.get("recycled_from"):
            # Recycled assets already have pixels; rewriting the prompt would not change them.
            d.quality["concept"] = assess_concept(d)
        else:
            rounds = 0
            while True:
                result = assess_concept(d)
                result["rounds"] = rounds
                d.quality["concept"] = result
                if result["status"] != "needs_revision" or rounds >= max_rounds:
                    break
                before = d.prompt
                _record(d, {
                    "type": "revision",
                    "source": "quality_precheck",
                    "round": rounds + 1,
                    "issues": result["issues"],
                    "feedback": result["feedback"],
                })
                d.brief = build_brief(d, research=research, product_types=product_types, rework=True)
                d.prompt = render_prompt(d.brief)
                rounds += 1
                summary["revised"] += 1
                if d.prompt == before:
                    d.quality["concept"] = dict(assess_concept(d), rounds=rounds)
                    break
        summary["checked"] += 1
        status = d.quality["concept"]["status"]
        summary["passed" if status == "pass" else status] += 1
    return summary


def revise_for_compliance(design, research: Optional[Dict] = None, product_types=None) -> bool:
    """Rework a compliance-flagged design using the compliance notes as
    concrete feedback. Returns True only if the prompt actually changed and
    the rework budget allows it; the caller must then re-run compliance.
    Recycled assets (existing pixels) are never reworked here."""
    if design.lineage.get("recycled_from"):
        return False
    brief = design.brief or {}
    if int(brief.get("compliance_reworks", 0)) >= MAX_COMPLIANCE_REWORKS:
        return False
    notes = (design.compliance_notes or "").lower()
    feedback = []
    avoid = list(brief.get("avoid", []))
    variation = int(brief.get("variation", 0))
    if "trademark" in notes:
        feedback.append("Remove any brand-like or slogan phrasing; use purely descriptive imagery.")
        avoid.append("brand-like slogans or phrases")
    if "similar" in notes:
        feedback.append("Move away from the similar existing listing: new focal motif and a different style direction.")
        avoid.append("compositions resembling the flagged similar listing")
        variation += 1
    if not feedback:
        feedback.append("Address the compliance note with a distinct, generic composition.")
        variation += 1
    _record(design, {"type": "revision", "source": "compliance", "notes": design.compliance_notes, "feedback": feedback})
    before = design.prompt
    design.brief = dict(brief, avoid=list(dict.fromkeys(avoid)), variation=variation,
                        compliance_reworks=int(brief.get("compliance_reworks", 0)) + 1)
    if not design.brief.get("concept"):
        design.brief["concept"] = design.niche
    new_brief = build_brief(design, research=research, product_types=product_types, rework=True)
    design.brief = new_brief
    design.prompt = render_prompt(new_brief)
    return design.prompt != before


def _png_size(path: Path):
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def assess_generated_image(design, assessor: Optional[Callable] = None) -> Dict:
    """Assessment of an *actual* generated image, distinct from the concept
    pre-check. Never generates or regenerates images."""
    uri = design.image_uri or ""
    base = {"kind": "image_assessment", "image_inspected": False, "limitations": IMAGE_LIMITATIONS}
    if not uri:
        return dict(base, status="no_image", reason="no image was generated for this design")
    if uri.startswith("sim://"):
        return dict(base, status="simulated", reason="simulated asset: no pixels exist to assess")
    path = Path(uri)
    if not path.is_file():
        return dict(base, status="missing_file", reason="image file not found on disk")
    size = None
    try:
        size = _png_size(path)
    except OSError:
        size = None
    file_checks = {
        "png_header": size is not None,
        "width": size[0] if size else None,
        "height": size[1] if size else None,
        "min_side_ok": bool(size and min(size) >= 1024),
    }
    result = dict(base, file_checks=file_checks)
    if assessor is None:
        return dict(result, status="not_assessed", reason="no image assessor configured (offline file checks only)")
    try:
        verdict = assessor(str(path), design.brief or {})
        return dict(result, status="assessed", image_inspected=True, verdict=verdict,
                    assessor=getattr(assessor, "__name__", "custom"))
    except Exception as exc:  # assessor optional: degrade to file checks
        return dict(result, status="assessor_unavailable", reason=f"image assessor failed: {exc}")
