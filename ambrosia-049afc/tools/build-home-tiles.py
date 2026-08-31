#!/usr/bin/env python3
"""Home-page media tiles for the MWG 108 entry list.

The tiles render at 8vw square (~115px, ~230px at 2x), but the source frames
run to 7723x11585 — sixteen of the campaign-board frames would be a 12MB entry
page. So each section gets sixteen 400px square crops written to home/, picked
round-robin across that section's cases so one shoot cannot fill a whole fan.

Idempotent: rerun after adding frames to data.js and it rebuilds the set.
"""
import json, os
from PIL import Image, ImageOps

SITE = "/sessions/affectionate-nice-cannon/mnt/Ambrosia/Strategy & Decks/Ambrosia — The Work (site)"
OUT = os.path.join(SITE, "home")
SIZE, QUALITY, PER_SECTION = 400, 80, 16
os.makedirs(OUT, exist_ok=True)
os.chdir(SITE)

raw = open("data.js").read()
d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])

manifest = {}
for sec in d["sections"]:
    # one bucket per case, so the round-robin can interleave them
    buckets = []
    for c in d["cases"]:
        if c["sec"] != sec["id"]:
            continue
        b = [p for p in ("frames/%s/%s" % (c["id"], f["f"]) for f in (c.get("frames") or []))
             if os.path.exists(p)]
        card = "plates/cs-card/%s.jpg" % c["id"]
        if not b and os.path.exists(card):
            b = [card]
        if b:
            buckets.append(b)
    if not buckets:
        print("  !! no art for", sec["id"]); continue

    picked, r = [], 0
    while len(picked) < PER_SECTION:
        added = False
        for b in buckets:
            if r < len(b):
                picked.append(b[r]); added = True
                if len(picked) == PER_SECTION: break
        if not added:                      # pool smaller than 16 — wrap around
            if not picked: break
            picked += picked[:PER_SECTION - len(picked)]
            break
        r += 1

    names = []
    for i, src in enumerate(picked[:PER_SECTION], 1):
        dst = "home/%s-%02d.jpg" % (sec["id"], i)
        try:
            im = Image.open(src)
            im = ImageOps.exif_transpose(im).convert("RGB")
            im = ImageOps.fit(im, (SIZE, SIZE), Image.LANCZOS, centering=(0.5, 0.45))
            im.save(dst, "JPEG", quality=QUALITY, optimize=True, progressive=True)
            names.append(os.path.basename(dst))
        except Exception as e:
            print("  !! %s: %s" % (src, e))
    manifest[sec["id"]] = names
    kb = sum(os.path.getsize("home/" + n) for n in names) / 1024
    print("%-11s %2d tiles  %5.0f KB total  (from %d cases)" % (sec["id"], len(names), kb, len(buckets)))

json.dump(manifest, open("home/manifest.json", "w"), indent=1)
tot = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
print("\nhome/ total: %.0f KB across %d files" % (tot / 1024, len(os.listdir(OUT))))
