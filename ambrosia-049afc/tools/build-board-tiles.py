#!/usr/bin/env python3
"""Drift tiles for the campaign reference boards.

campaign.html pins the board and drifts every frame across the stage at once.
The frames are reference plates at full size — amb-board-gifting alone is 15MB,
one of its frames 7723x11585 — so the stage gets 1000px copies instead. The
originals stay where they are and remain the lightbox's source; a missing tile
falls back to the original in the page.

Run after adding or replacing board frames in data.js:
    python3 tools/build-board-tiles.py
"""
import json, os
from PIL import Image, ImageOps

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX, QUALITY = 1000, 82
os.chdir(SITE)

raw = open("data.js", encoding="utf-8").read()
d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
boards = [c for c in d["cases"] if c["id"].startswith("amb-board-")]
if not boards:
    raise SystemExit("no boards in data.js")

for b in boards:
    out = os.path.join("boards", b["id"])
    os.makedirs(out, exist_ok=True)
    total = before = 0
    for f in b.get("frames", []):
        src = os.path.join("frames", b["id"], f["f"])
        if not os.path.exists(src):
            print("  missing:", src); continue
        dst = os.path.join(out, os.path.splitext(f["f"])[0] + ".jpg")
        im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        im.thumbnail((MAX, MAX), Image.LANCZOS)
        im.save(dst, "JPEG", quality=QUALITY, optimize=True, progressive=True)
        total += os.path.getsize(dst); before += os.path.getsize(src)
    print("%-20s %2d tiles  %6.0f KB  (from %.1f MB)"
          % (b["id"], len(b.get("frames", [])), total / 1024, before / 1048576))
