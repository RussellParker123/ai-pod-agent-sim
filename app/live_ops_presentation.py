"""Presentation helpers for the Live Ops page."""

import html

from app.sim.characters import DrCypher
from app.utils.dr_cipher import get_dr_cipher_svg


MANAGER_NODE = ("manager", "🧠", "DR. CYPHER · MANAGER")
STAGE_NODES = [
    ("etsy_connect", "📡", "ETSY UPLINK"),
    ("trend", "📈", "TREND SCANNER"),
    ("prompt", "⌨️", "PROMPT FORGE"),
    ("compliance", "🛡️", "COMPLIANCE DAEMON"),
    ("mockup", "🧵", "MOCKUP RENDER"),
    ("pricing", "💠", "PRICE CORE"),
    ("image_team", "🧑‍🤝‍🧑", "ART TEAM ASSEMBLY"),
    ("image", "🖼️", "ART SYNTH · OPENAI"),
    ("etsy", "🛰️", "ETSY DRAFT"),
    ("printful", "🏭", "PRINTFUL FAB LINK"),
]

STAGE_LOCATIONS = {
    "etsy_connect": "command",
    "trend": "trend",
    "prompt": "prompt",
    "compliance": "compliance",
    "mockup": "mockup",
    "pricing": "pricing",
    "manager": "approval",
    "image_team": "image",
    "image": "image",
    "etsy": "approval",
    "manager_publish": "approval",
    "printful": "approval",
    "complete": "command",
}

STAGE_STATUSES = ("idle", "active", "done", "error")
ENTRY_STATUSES = {
    "pending_approval": "Draft · awaiting review",
    "live": "Published",
    "rejected": "Rejected",
}


def stage_status(stage_state: dict, key: str) -> str:
    """Return a safe visible state label for a known stage."""
    status = stage_state.get(key, "idle")
    return status if status in STAGE_STATUSES else "idle"


def _node_html(key: str, icon: str, label: str, stage_state: dict) -> str:
    status = stage_status(stage_state, key)
    return (
        f'<div class="node {status}" aria-label="{html.escape(label)}: {status.upper()}">'
        f'<div class="icon" aria-hidden="true">{icon}</div>'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="status-label">{status.upper()}</div></div>'
    )


def _artist_room_html(active: bool) -> str:
    if not active:
        return ""
    return (
        '<div class="artist-room" role="status" aria-label="Live image generation: animated art agents painting">'
        '<div class="studio-scene" aria-hidden="true">'
        '<div class="easel"><span class="paint-stroke stroke-one"></span><span class="paint-stroke stroke-two"></span>'
        '<span class="paint-stroke stroke-three"></span></div>'
        '<div class="artist artist-one">👩‍🎨<i class="brush"></i></div>'
        '<div class="artist artist-two">🧑‍🎨<i class="brush"></i></div></div>'
        '<div><div class="artist-room-title">🎨 LIVE ARTIST ROOM · PAINTING IN PROGRESS</div>'
        '<div class="artist-room-note">Animated studio activity · completed images appear in the live art feed below</div></div>'
        '</div>'
    )


def render_live_console(stage_state: dict, log_lines: list, character: dict = None) -> str:
    """Build self-contained console markup; logs are escaped at the render boundary."""
    character_status = stage_status({"manager": (character or {}).get("status", "idle")}, "manager")
    character = DrCypher.from_dict(character).to_dict()
    manager = _node_html(*MANAGER_NODE, stage_state)
    nodes = "".join(_node_html(*node, stage_state) for node in STAGE_NODES)
    avatar = get_dr_cipher_svg().replace(
        'style="max-width: 280px; max-height: 420px;"',
        'style="width:76px;height:114px;max-width:100%;"',
    )
    presence = (
        f'<div class="cypher-presence {character_status}" role="group" '
        f'aria-label="{html.escape(character["display_name"])} live character">'
        f'<div class="cypher-avatar" role="img" aria-label="{html.escape(character["display_name"])}">{avatar}</div>'
        '<div class="cypher-details">'
        f'<div class="cypher-name">🧪 {html.escape(character["display_name"])} · LIVE</div>'
        f'<div class="cypher-meta">{html.escape(character["title"])} · {html.escape(character["mood"])} · '
        f'{html.escape(character["location"])}</div>'
        f'<div class="cypher-activity">{html.escape(character["activity"])}</div>'
        f'<div class="cypher-line">“{html.escape(character["line"])}”</div>'
        '</div></div>'
    )
    log_html = "".join(
        f'<div class="line">{html.escape(str(line))}</div>' for line in log_lines
    ) or '<div class="line">&gt; standing by...</div>'
    return (
        """<style>
        *{box-sizing:border-box}
        .cyber-wrap{width:100%;overflow:hidden;background:linear-gradient(135deg,#0a0e27,#1a1a3e 55%,#2d1b4e);
          border:1px solid #00ccff;border-radius:14px;padding:clamp(10px,2vw,18px);color:#e7f0ff;
          font-family:'Courier New',monospace;box-shadow:0 0 18px #00ccff33}
        .cyber-title{color:#00ff41;letter-spacing:clamp(1px,.3vw,3px);font-size:clamp(12px,2vw,16px);
          margin-bottom:12px;text-shadow:0 0 8px #00ff4180}
        .command-deck{display:flex;justify-content:center;margin-bottom:12px}
        .command-deck .node{max-width:340px;width:100%;border:2px solid #ff6b9d}
        .cypher-presence{display:flex;align-items:center;gap:12px;margin:0 0 12px;padding:10px 14px;
          border:1px solid #ff6b9d88;border-radius:12px;background:linear-gradient(110deg,#2d1b4e,#1a2d4e);
          color:#e7f0ff;min-height:128px}
        .cypher-presence.active{border-color:#ffaa00;box-shadow:0 0 12px #ffaa0066}
        .cypher-presence.done{border-color:#00ff41}
        .cypher-presence.error{border-color:#ff6b9d;box-shadow:0 0 12px #ff6b9d66}
        .cypher-avatar{flex:0 0 76px;line-height:0}
        .cypher-name{color:#ff6b9d;font-weight:bold;letter-spacing:.5px}
        .cypher-meta{font-size:11px;color:#9edfff;margin-top:4px}
        .cypher-activity{font-size:12px;color:#9dffc1;margin-top:6px}
        .cypher-line{font-size:12px;margin-top:4px;overflow-wrap:anywhere}
        .cyber-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,132px),1fr));gap:9px}
        .node{min-width:0;border:1px solid #00ccff88;border-radius:11px;padding:10px 6px;text-align:center;
          background:linear-gradient(145deg,#1a2d4e,#2d1b4e);overflow-wrap:anywhere}
        .node .icon{font-size:22px}
        .node .label{font-size:clamp(9px,1.3vw,11px);color:#c6dbff;letter-spacing:.5px;margin-top:4px}
        .status-label{display:inline-block;margin-top:7px;padding:2px 7px;border-radius:12px;
          font-size:10px;font-weight:bold;letter-spacing:.6px;color:#e7f0ff;background:#475569}
        .node.active{border-color:#ffaa00;box-shadow:0 0 12px #ffaa0066}
        .node.active .status-label{color:#1a1a3e;background:#ffaa00}
        .node.done{border-color:#00ff41}
        .node.done .status-label{color:#0a0e27;background:#00ff41}
        .node.error{border-color:#ff6b9d;box-shadow:0 0 12px #ff6b9d66}
        .node.error .status-label{color:#fff;background:#a91b54}
        .artist-room{display:flex;align-items:center;gap:14px;margin:0 0 12px;padding:9px 12px;
          border:1px solid #ff6b9d;border-radius:11px;background:linear-gradient(110deg,#302040,#1a2d4e);
          box-shadow:0 0 14px #ff6b9d33}
        .studio-scene{position:relative;flex:0 0 150px;height:72px;overflow:hidden;border-bottom:3px solid #8b6b3d;
          border-radius:7px 7px 2px 2px;background:linear-gradient(#283657 0 72%,#70543b 72%)}
        .easel{position:absolute;left:58px;top:9px;width:34px;height:31px;border:2px solid #f2d7a4;
          border-radius:3px;background:#17213b}
        .easel:after{position:absolute;content:"";left:15px;top:29px;height:28px;border-left:2px solid #d4b08c}
        .paint-stroke{position:absolute;height:4px;width:7px;border-radius:5px;animation:paint-stroke .9s ease-in-out infinite alternate}
        .stroke-one{left:5px;top:7px;background:#ff6b9d}.stroke-two{left:17px;top:12px;background:#00ccff;animation-delay:.2s}
        .stroke-three{left:9px;top:21px;background:#ffaa00;animation-delay:.4s}
        .artist{position:absolute;bottom:0;font-size:25px;line-height:1;animation:artist-bob .7s ease-in-out infinite alternate}
        .artist-one{left:22px}.artist-two{right:17px;animation-delay:.3s}
        .brush{position:absolute;right:-7px;top:13px;width:19px;border-top:2px solid #f2d7a4;
          transform:rotate(-28deg);transform-origin:left;animation:brush-paint .55s ease-in-out infinite alternate}
        .artist-room-title{font-weight:bold;color:#ffb6d0;letter-spacing:.4px}
        .artist-room-note{font-size:11px;color:#b8c7e8;margin-top:5px}
        @keyframes artist-bob{to{transform:translateY(-3px)}}
        @keyframes brush-paint{to{transform:rotate(16deg)}}
        @keyframes paint-stroke{to{transform:scaleX(.6);opacity:.65}}
        .term{background:#070914;border:1px solid #00ccff88;border-radius:8px;padding:9px 10px;
          height:112px;margin-top:12px;overflow:auto;font-size:12px;color:#9dffc1;overflow-wrap:anywhere}
        .term .line{padding:1px 0}
        @media(prefers-reduced-motion:no-preference){.node.active{animation:live-pulse 1.5s ease-in-out infinite}}
        @keyframes live-pulse{50%{box-shadow:0 0 14px #ffaa0088}}
        @media(prefers-reduced-motion:reduce){.dr-cipher,.dr-cipher-glow,.artist,.brush,.paint-stroke{animation:none!important}}
        @media(max-width:420px){.cyber-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        </style>"""
        + '<div class="cyber-wrap">'
        + '<div class="cyber-title">⚡ LIVE OPS ARENA · EVENT-DRIVEN STAGE STATUS ⚡</div>'
        + f'<div class="command-deck">{manager}</div>'
        + presence
        + _artist_room_html(stage_status(stage_state, "image") == "active")
        + f'<div class="cyber-grid">{nodes}</div>'
        + f'<div class="term" role="log" aria-label="Live event log">{log_html}</div>'
        + "</div>"
    )


def entry_status(entry: dict) -> str:
    """Map persisted pipeline status to an explicit, non-inferred UI label."""
    return ENTRY_STATUSES.get(entry.get("status"), "Other recorded status")


def registry_counts(entries: list) -> dict:
    """Count only explicit statuses present in locally stored live entries."""
    counts = {"drafts": 0, "published": 0, "rejected": 0, "other": 0}
    for entry in entries:
        status = entry.get("status")
        bucket = {
            "pending_approval": "drafts",
            "live": "published",
            "rejected": "rejected",
        }.get(status, "other")
        counts[bucket] += 1
    return counts
