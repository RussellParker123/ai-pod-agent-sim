"""Shop-branding agent: generates logo/banner/avatar images and shop
text (tagline, announcement, shop story) for the real NeuralArtTreasures
Etsy shop, and applies whichever parts Etsy's API actually allows.

Etsy's Open API v3 only lets a shop update its `title` (tagline),
`announcement`, `sale_message`, and `digital_sale_message` via
PATCH /shops/{shop_id} (see etsy_client.update_shop). There is NO API for
uploading a shop icon, banner image, "shop story", or seller/about photo —
those are confirmed web-UI-only (verified against this shop's own
get_shop() response, which shows icon_url_fullxfull/image_url_760x100 are
null and have no corresponding writable field in the API). So this agent:

  1. Generates all the creative content with AI (text + images).
  2. Applies the title/announcement live via the Etsy API (real, verified).
  3. Saves the logo/banner/avatar images locally for the user to upload
     themselves via the exact Etsy settings URLs, since the API can't do
     that last step.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from app.integrations import etsy_client, openai_image, openai_text
from app.integrations.config import DATA_DIR

BRAND_DIR = DATA_DIR / "branding"

SHOP_NAME = "NeuralArtTreasures"
SHOP_NICHE = (
    "AI-generated art prints on everyday products (mugs, t-shirts, totes) — "
    "nature, outdoor, and cyberpunk-inspired designs"
)

UPLOAD_URLS = {
    "logo": "https://www.etsy.com/your/shops/me/settings/your-shop/shop-basics#shopIcon",
    "banner": f"https://www.etsy.com/shop/{SHOP_NAME}/edit?open_modal=banner",
    "seller_photo": f"https://www.etsy.com/shop/{SHOP_NAME}/edit?open_modal=photo",
    "story": "https://www.etsy.com/your/shops/me/settings/your-shop/shop-basics#shopStory",
}


def generate_branding_text() -> Dict[str, str]:
    """Generates shop title (tagline), announcement, and a shop-story
    paragraph via GPT. Raises NotConfiguredError if no OpenAI key is set."""
    system = (
        "You write concise, upbeat Etsy shop copy for a print-on-demand shop "
        "that sells AI-generated art on mugs, t-shirts, and totes."
    )
    user = (
        f"Shop name: {SHOP_NAME}\n"
        f"What they sell: {SHOP_NICHE}\n\n"
        "Write JSON with exactly these keys:\n"
        '  "title": a shop tagline, under 55 characters, no quotes\n'
        '  "announcement": a 1-2 sentence welcome banner for the shop homepage, under 160 characters\n'
        '  "story": a warm 3-4 sentence "About" story for the shop story section, '
        "mentioning the designs are AI-generated and printed on demand"
    )
    result = openai_text.chat_json(system, user)
    return {
        "title": str(result["title"]).strip()[:55],
        "announcement": str(result["announcement"]).strip()[:160],
        "story": str(result["story"]).strip(),
    }


def generate_branding_images() -> Dict[str, Path]:
    """Generates a logo, banner, and seller/avatar image via OpenAI image
    gen and saves them under data/branding/. Raises NotConfiguredError if
    no OpenAI key is set."""
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    jobs = {
        "logo": (
            f"A clean, modern, minimalist square logo icon for an Etsy shop called "
            f"'{SHOP_NAME}' that sells AI-generated nature/outdoor/cyberpunk art prints "
            "on mugs, t-shirts, and totes. Bold simple shape, no text, flat vector style, "
            "vivid cyan/purple accent colors on a dark background, works well as a tiny icon.",
            "1024x1024",
        ),
        "banner": (
            f"A wide shop banner image for an Etsy storefront called '{SHOP_NAME}', showcasing "
            "AI-generated nature and cyberpunk-style art prints on mugs and apparel, laid out "
            "attractively, vivid cyan/purple neon accents on a dark background, no text overlay.",
            "1536x1024",
        ),
        "seller_photo": (
            f"A friendly, approachable brand mascot avatar image for the Etsy shop '{SHOP_NAME}' "
            "— a stylized AI-artist robot/fox character in a cozy studio, warm and inviting, "
            "square framing, suitable as a seller profile photo.",
            "1024x1024",
        ),
    }
    out: Dict[str, Path] = {}
    for key, (prompt, size) in jobs.items():
        out_path = BRAND_DIR / f"{key}.png"
        openai_image.generate_image(prompt, out_path, size=size)
        out[key] = out_path
    return out


def apply_shop_text(shop_id: int, title: str, announcement: str) -> dict:
    """Live-applies the API-settable fields (title + announcement) to the
    real Etsy shop and returns Etsy's updated shop record."""
    return etsy_client.update_shop(shop_id, title=title, announcement=announcement)
