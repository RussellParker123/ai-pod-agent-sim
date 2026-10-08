"""Branding agent: drafts shop name, logo, banner and story for human review."""
import argparse
import random
from typing import Dict, List

from app.sim.utils import save_json, timestamp

NAME_PARTS = {
    "cozy autumn": ("Maple", "Hearth"),
    "pet lovers": ("Paw", "Whisker"),
    "minimalist motivation": ("Quiet", "Compass"),
    "retro outdoors": ("Trailhead", "Pine"),
    "bookish humor": ("Margin", "Bookmark"),
    "coffee culture": ("Brew", "Bean"),
}
SUFFIXES = ["Studio", "& Co", "Prints", "Goods", "Workshop"]


def branding_agent(niches: List[str], seed: int = None) -> Dict:
    rng = random.Random(seed)
    words = [w for n in niches for w in NAME_PARTS.get(n, (n.split()[0].title(),))]
    names = []
    while len(names) < 5:
        n = f"{rng.choice(words)} {rng.choice(SUFFIXES)}"
        if n not in names:
            names.append(n)
    # Etsy shop names: 4-20 chars, letters/numbers only, no spaces
    etsy_names = [("".join(c for c in n if c.isalnum()))[:20] for n in names]
    focus = ", ".join(niches)
    return {
        "shop_name": {"suggestions": names, "etsy_safe": etsy_names, "pick": names[0]},
        "logo": {
            "size": "500x500 px (shown as a circle)",
            "prompt": f"Simple, original vector logo mark for '{names[0]}', themes: {focus}; "
            "flat colors, high contrast, readable at small size, no text clutter, no trademarks",
        },
        "banner": {
            "size": "3360x840 px",
            "prompt": f"Wide banner showing mugs and t-shirts in a stylized lifestyle flat-lay, themes: {focus}; "
            "leave empty space on the left for the shop name, original art only",
        },
        "story": (
            f"Hi, welcome to {names[0]}! I design original art inspired by {focus}. "
            "Each design starts as an idea and is developed with the help of AI art tools, then refined "
            "and checked for originality. Items are printed on demand and made just for you, "
            "so nothing is wasted. Thank you for supporting a small shop."
        ),
        "notes": "Draft for human review. Disclose AI-generated art on Etsy. Apply these in Shop Manager.",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--niches", nargs="*", default=list(NAME_PARTS))
    a = ap.parse_args()
    out = branding_agent(a.niches)
    print(f"Branding saved: {save_json(out, f'branding_{timestamp()}.json')}")
    print("Shop name suggestions:", ", ".join(out["shop_name"]["suggestions"]))
