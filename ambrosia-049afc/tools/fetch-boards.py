#!/usr/bin/env python3
"""
fetch-boards.py — build the moodboard section from tools/boards-manifest.json.

No Pinterest API, no app, no token, no approval. The two boards are public, so
their images are ordinary public URLs; the manifest already holds them.

    python3 tools/fetch-boards.py
    python3 tools/fetch-boards.py --check     # verify every URL resolves, download nothing

What it does, per board:
  1. downloads each image into frames/<case-id>/NN.<ext>
  2. reads real pixel dimensions from the file header (jpg / png / webp)
  3. rewrites ONLY the `frames` array of that case in data.js
  4. writes frames/<case-id>/sources.json — pin link per frame, for attribution

Safe to re-run: each frame directory is rebuilt from scratch, and two runs in a
row produce a byte-identical data.js. If a board's downloads all fail, data.js
is left untouched rather than emptied.
"""

import argparse
import json
import shutil
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
MANIFEST = SITE / "tools" / "boards-manifest.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def die(msg):
    print(f"\n  ✗ {msg}\n", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- dimensions

def jpeg_size(f):
    if f.read(2) != b"\xff\xd8":
        return None
    while True:
        b = f.read(1)
        while b and b != b"\xff":
            b = f.read(1)
        marker = f.read(1)
        while marker == b"\xff":
            marker = f.read(1)
        if not marker:
            return None
        if marker[0] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                         0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            f.read(3)
            h, w = struct.unpack(">HH", f.read(4))
            return w, h
        seg = f.read(2)
        if len(seg) < 2:
            return None
        f.seek(struct.unpack(">H", seg)[0] - 2, 1)


def png_size(f):
    head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def webp_size(f):
    head = f.read(30)
    if head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return None
    fmt = head[12:16]
    if fmt == b"VP8X":
        w = int.from_bytes(head[24:27], "little") + 1
        h = int.from_bytes(head[27:30], "little") + 1
        return w, h
    if fmt == b"VP8L":
        b = head[21:25]
        n = int.from_bytes(b, "little")
        return (n & 0x3FFF) + 1, ((n >> 14) & 0x3FFF) + 1
    if fmt == b"VP8 ":
        return struct.unpack("<HH", head[26:30])[0] & 0x3FFF, \
               struct.unpack("<HH", head[26:30])[1] & 0x3FFF
    return None


def measure(path):
    """Real pixel size, whatever the format. None if unreadable."""
    for reader in (jpeg_size, png_size, webp_size):
        try:
            with open(path, "rb") as f:
                got = reader(f)
            if got and got[0] and got[1]:
                return got
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- data.js

def read_data():
    raw = (SITE / "data.js").read_text(encoding="utf-8")
    return json.loads(raw[raw.index("{"):].rstrip().rstrip(";"))


def write_data(d):
    """Match data.js's existing format exactly, or the diff is the whole file."""
    body = json.dumps(d, ensure_ascii=True, separators=(", ", ": "))
    (SITE / "data.js").write_text("window.WORK=" + body + ";", encoding="utf-8")


# ---------------------------------------------------------------- main

def check(man):
    print("\n  checking every image URL resolves — downloading nothing\n")
    bad = 0
    for board in man["boards"]:
        print(f"  {board['name']}")
        for i, pin in enumerate(board["pins"], 1):
            req = urllib.request.Request(pin["image"], headers=UA, method="HEAD")
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    size = r.headers.get("content-length")
                    kb = f"{int(size)//1024}KB" if size else "?"
                    print(f"    {i:02d} · {r.status} {kb:>7}  {pin['image'].rsplit('/',1)[1]}")
            except urllib.error.HTTPError as e:
                bad += 1
                print(f"    {i:02d} · HTTP {e.code}  {pin['image']}", file=sys.stderr)
            except Exception as e:
                bad += 1
                print(f"    {i:02d} · {type(e).__name__}  {pin['image']}", file=sys.stderr)
        print()
    if bad:
        die(f"{bad} image(s) did not resolve. Pinterest may have rotated the URL — "
            "re-harvest the manifest before running the real fetch.")
    print("  ✓ all URLs resolve\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="HEAD every image URL and stop. Writes nothing.")
    args = ap.parse_args()

    if not MANIFEST.exists():
        die(f"No manifest at {MANIFEST}")
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))

    if args.check:
        return check(man)

    d = read_data()
    cases = {c["id"]: c for c in d["cases"]}

    for board in man["boards"]:
        cid = board["case"]
        if cid not in cases:
            die(f"data.js has no case '{cid}'.")
        print(f"\n  {board['name']}  →  {cid}")

        out = SITE / "frames" / cid
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)

        frames, sources, n = [], [], 0
        for pin in board["pins"]:
            url = pin["image"]
            ext = url.rsplit(".", 1)[1].lower()
            n += 1
            name = f"{n:02d}.{ext}"
            dest = out / name
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
                    shutil.copyfileobj(r, f)
            except Exception as e:
                dest.unlink(missing_ok=True)
                n -= 1
                print(f"      · failed {name}: {e}", file=sys.stderr)
                continue

            if dest.stat().st_size == 0:
                dest.unlink(); n -= 1
                print(f"      · failed {name}: empty", file=sys.stderr)
                continue

            wh = measure(dest)
            if not wh:
                print(f"      · {name}: could not read dimensions, using 0×0", file=sys.stderr)
            w, h = wh or (0, 0)
            frames.append({"f": name, "w": w, "h": h})
            sources.append({"f": name, "pin": pin["pin_url"], "image": url})
            print(f"      · {name}  {w}×{h}")

        if board["pins"] and not frames:
            die(f"'{board['name']}': {len(board['pins'])} images and not one downloaded.\n"
                "    data.js NOT touched. Check the network and re-run.")

        (out / "sources.json").write_text(
            json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")
        cases[cid]["frames"] = frames
        print(f"    → {len(frames)} frames in frames/{cid}/")

    write_data(d)
    total = sum(len(cases[b["case"]]["frames"]) for b in man["boards"])
    print(f"\n  ✓ data.js updated — {total} frames across {len(man['boards'])} boards")
    print("    Open map.html?s=moodboard and click into either board.\n")


if __name__ == "__main__":
    main()
