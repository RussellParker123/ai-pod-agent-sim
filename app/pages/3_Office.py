"""Animated office view: each agent has a desk; the active one lights up and talks."""
import json
import time
from pathlib import Path
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

AGENTS = [
    ("🔎", "Trend Agent", "Market research"),
    ("✍️", "Prompt Agent", "Original prompts"),
    ("🎨", "Image Agent", "Art generation"),
    ("🛡️", "Compliance Agent", "Trademark & similarity"),
    ("👕", "Mockup Agent", "Mugs, shirts, totes"),
    ("💲", "Pricing Agent", "Margins"),
    ("🧑‍💼", "Manager", "Oversight & greenlight"),
]

CSS = """
<style>
 body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#1e2430;}
 .office{background:#e9e2d0;border:6px solid #3b4252;border-radius:14px;padding:14px;}
 .mgr-room{background:rgba(120,180,220,.25);border:3px solid #6fa8c9;border-radius:12px;padding:8px;
   display:flex;justify-content:center;margin-bottom:14px;}
 .floor{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
 .desk{position:relative;background:#c9a66b;border-radius:10px;padding:10px;text-align:center;
   box-shadow:0 4px 0 #8b6b3d;min-height:120px;transition:all .3s;}
 .desk.active{background:#ffe08a;box-shadow:0 0 18px 4px #ffb300;transform:translateY(-3px);}
 .monitor{background:#222;color:#7CFC9A;border-radius:6px;margin:0 auto 6px;width:70px;padding:4px;
   font-family:monospace;font-size:14px;border:3px solid #555;}
 .avatar{font-size:38px;line-height:1.1;}
 .active .avatar{animation:bob .8s infinite ease-in-out;}
 .name{font-weight:700;font-size:13px;color:#2b2b2b;}
 .role{font-size:11px;color:#444;}
 .bubble{position:absolute;top:-34px;left:50%;transform:translateX(-50%);background:#fff;color:#222;
   border:2px solid #333;border-radius:10px;padding:4px 8px;font-size:11px;width:190px;z-index:5;}
 .bubble:after{content:'';position:absolute;bottom:-8px;left:50%;border:6px solid transparent;border-top-color:#333;}
 .mgr-room .desk{width:260px;}
 @keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
</style>
"""


def desk(i, active, bubble, count):
    emoji, name, role = AGENTS[i]
    cls = "desk active" if i == active else "desk"
    b = f'<div class="bubble">{bubble}</div>' if i == active else ""
    return (f'<div class="{cls}">{b}<div class="monitor">{count}</div>'
            f'<div class="avatar">{emoji}</div><div class="name">{name}</div><div class="role">{role}</div></div>')


def office_html(active, bubbles, counts):
    mgr = desk(6, active, bubbles[6], counts[6])
    workers = "".join(desk(i, active, bubbles[i], counts[i]) for i in range(6))
    return f'{CSS}<div class="office"><div class="mgr-room">{mgr}</div><div class="floor">{workers}</div></div>'


files = sorted(DATA_DIR.glob("run_*.json")) if DATA_DIR.exists() else []
st.title("The Office")
if not files:
    st.warning("No runs yet. Run: python -m app.sim.run_simulation")
    st.stop()

run = st.selectbox("Select run", [f.name for f in files], index=len(files) - 1)
payload = json.loads((DATA_DIR / run).read_text(encoding="utf-8"))
mgr = payload.get("manager", {})
df = pd.DataFrame(payload["designs"])
dec = pd.DataFrame(mgr.get("decisions", []))


def n(stage, action):
    return int(((dec["stage"] == stage) & (dec["action"] == action)).sum()) if not dec.empty else 0


n_designs = len(df)
prod = df["product_type"].value_counts().to_dict() if n_designs else {}
bc = mgr.get("batch", {}).get("counts", {})
status = mgr.get("batch", {}).get("status", "n/a")

bubbles = [
    f"Manager kept {n_designs} trending designs, dropped {n('trend', 'drop')}.",
    f"Wrote {n_designs} original prompts. No logos, no characters!",
    f"Generated {n_designs} images (simulated).",
    f"Re-checked {n('compliance', 'retry')} flagged, rejected {n('compliance', 'reject')}.",
    "Mockups: " + ", ".join(f"{v} {k}" for k, v in prod.items()),
    f"Priced everything. Repriced {n('pricing', 'reprice')} below margin floor.",
    f"GREENLIGHT {bc.get('GREENLIGHT', 0)} | HOLD {bc.get('HOLD', 0)} | BLOCK {bc.get('BLOCK', 0)}. Batch: {status}",
]
counts = [n_designs, n_designs, n_designs, n_designs, n_designs, n_designs, bc.get("GREENLIGHT", 0)]

step = st.slider("Pipeline step (0 = idle)", 0, 7, 0)
play = st.button("▶ Play full run")
slot = st.empty()

if play:
    for s in range(1, 8):
        with slot:
            components.html(office_html(s - 1, bubbles, counts), height=620)
        time.sleep(1.4)
else:
    with slot:
        components.html(office_html(step - 1, bubbles, counts), height=620)

st.caption("Use the Review page to cancel or override anything the Manager greenlit.")
