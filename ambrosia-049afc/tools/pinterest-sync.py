#!/usr/bin/env python3
"""
pinterest-sync.py — pull the two Ambrosia moodboards off Pinterest once, at build
time, and write them into the site as ordinary frames.

The site stays static. Nothing here runs in the browser, no Pinterest JavaScript
ends up on the page, and no token is needed to view the result.

    export PINTEREST_TOKEN='...'          # never commit this, never paste it anywhere
    python3 tools/pinterest-sync.py

    python3 tools/pinterest-sync.py --dry-run    # uses tools/fixtures.json, no network

What it does:
  1. lists your boards, matches the two by name
  2. lists each board's pins
  3. downloads the largest image for each pin into frames/<case-id>/NN.jpg
  4. rewrites the `frames` array for those two cases in data.js
  5. writes frames/<case-id>/sources.json — pin id, link and domain per frame,
     so attribution survives. These are other people's photographs.

Re-running is safe: each case's frame directory is rebuilt from scratch, so the
site matches whatever the board holds today.
"""

import argparse
import json
import os
import re
import shutil
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.pinterest.com/v5"
SITE = Path(__file__).resolve().parent.parent

# board name on Pinterest  ->  case id in data.js
BOARDS = {
    "Ambrosia · The Usual": "amb-board-usual",
    "Ambrosia · Gifting": "amb-board-gifting",
}


# ---------------------------------------------------------------- http

def api(path, token, params=None):
    """One GET against the Pinterest API. Returns parsed JSON."""
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:600]
        # Pinterest puts the actual reason in the body. Always show it — a generic
        # "token expired" message sent us chasing the wrong thing once already.
        detail = f"\n\n    Pinterest said:\n    {body}" if body.strip() else ""
        tok = os.environ.get("PINTEREST_TOKEN", "")
        shape = f"{len(tok)} chars, starts '{tok[:5]}…'" if tok else "empty"
        if e.code == 401:
            die("401 Unauthorized on " + path + detail +
                f"\n\n    Token in the environment: {shape}"
                "\n    If the token looks right, the likely cause is that this app "
                "cannot call the API at all\n    while its access request is denied — "
                "the Generate-token button works, but the\n    token it issues is inert. "
                "That needs the app approved, not a new token.")
        if e.code == 403:
            die("403 Forbidden on " + path + detail +
                "\n\n    Usually a scope problem. Reading SECRET boards needs "
                "boards:read_secret and\n    pins:read_secret, which the instant token "
                "does not carry. Public boards need\n    only boards:read + pins:read.")
        if e.code == 429:
            die("429 Rate limited on " + path + detail +
                "\n\n    Trial access allows ~1,000 requests a day. Wait for the "
                "window and re-run.")
        die(f"HTTP {e.code} on {path}{detail}")


def paged(path, token, key="items"):
    """Walk a paginated collection to the end."""
    out, bookmark = [], None
    while True:
        params = {"page_size": 100}
        if bookmark:
            params["bookmark"] = bookmark
        data = api(path, token, params)
        out.extend(data.get(key) or [])
        bookmark = data.get("bookmark")
        if not bookmark:
            return out


# ---------------------------------------------------------------- images

def best_image(pin):
    """
    Largest still image on a pin. Pinterest hands back a dict of sizes keyed
    like '150x150', '600x', '1200x'; video pins carry a cover image instead.
    Returns (url, width, height) or None if the pin has no usable still.
    """
    media = pin.get("media") or {}
    images = media.get("images") or {}
    if not images and media.get("cover_image_url"):
        return (media["cover_image_url"], 0, 0)

    best = None
    for spec in images.values():
        if not isinstance(spec, dict) or not spec.get("url"):
            continue
        w = spec.get("width") or 0
        if best is None or w > best[1]:
            best = (spec["url"], w, spec.get("height") or 0)
    return best


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "98-work-site/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def jpeg_size(path):
    """Read width/height out of a JPEG header. Avoids a Pillow dependency."""
    with open(path, "rb") as f:
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


# ---------------------------------------------------------------- data.js

def read_data():
    raw = (SITE / "data.js").read_text(encoding="utf-8")
    start = raw.index("{")
    return json.loads(raw[start:].rstrip().rstrip(";"))


def write_data(d):
    """
    Rewrite data.js in exactly the format it already uses — one line,
    `window.WORK=`, ASCII-escaped, `, ` and `: ` separators. Anything else
    produces a diff the size of the file.
    """
    body = json.dumps(d, ensure_ascii=True, separators=(", ", ": "))
    (SITE / "data.js").write_text("window.WORK=" + body + ";", encoding="utf-8")


def domain_of(url):
    try:
        host = urllib.parse.urlparse(url or "").netloc
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


# ---------------------------------------------------------------- main

def die(msg):
    print(f"\n  ✗ {msg}\n", file=sys.stderr)
    sys.exit(1)


def sync_board(case_id, pins, verbose=True):
    """Download every pin's image into frames/<case_id>/ and return the frame list."""
    out_dir = SITE / "frames" / case_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    frames, sources, n = [], [], 0
    for pin in pins:
        img = best_image(pin)
        if not img:
            if verbose:
                print(f"      · skipped {pin.get('id')} — no still image")
            continue
        url, w, h = img
        n += 1
        name = f"{n:02d}.jpg"
        dest = out_dir / name
        try:
            download(url, dest)
        except Exception as e:
            # a half-written file would be numbered into the roll and render broken
            dest.unlink(missing_ok=True)
            n -= 1
            print(f"      · failed {pin.get('id')}: {e}", file=sys.stderr)
            continue

        if dest.stat().st_size == 0:
            dest.unlink()
            n -= 1
            print(f"      · failed {pin.get('id')}: empty response", file=sys.stderr)
            continue

        measured = jpeg_size(dest)
        if measured:
            w, h = measured
        frames.append({"f": name, "w": w, "h": h})

        link = pin.get("link") or ""
        sources.append({
            "f": name,
            "pin": f"https://www.pinterest.com/pin/{pin.get('id')}/",
            "link": link,
            "source": domain_of(link),
        })
        if verbose:
            print(f"      · {name}  {w}×{h}  {domain_of(link) or '—'}")

    (out_dir / "sources.json").write_text(
        json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="use tools/fixtures.json instead of the API — no token, no network")
    ap.add_argument("--check", action="store_true",
                    help="one call to /user_account to prove the token works, then stop. "
                         "Writes nothing. Use this to separate an auth problem from a board problem.")
    args = ap.parse_args()

    if args.check:
        token = os.environ.get("PINTEREST_TOKEN", "").strip()
        if not token:
            die("PINTEREST_TOKEN is not set.")
        print(f"\n  token: {len(token)} chars, starts '{token[:5]}…'")
        me = api("/user_account", token)
        print(f"  ✓ authenticated as: {me.get('username')} ({me.get('account_type')})")
        boards = paged("/boards", token)
        print(f"  ✓ /boards returned {len(boards)} board(s):")
        for b in boards:
            print(f"      · {b.get('name')}  [{b.get('privacy')}]")
        print()
        return

    if args.dry_run:
        fixtures = json.loads((SITE / "tools" / "fixtures.json").read_text(encoding="utf-8"))
        boards = fixtures["boards"]
        pins_by_board = fixtures["pins"]
        token = None
        print("\n  dry run — reading tools/fixtures.json, nothing leaves this machine\n")
    else:
        token = os.environ.get("PINTEREST_TOKEN", "").strip()
        if not token:
            die("PINTEREST_TOKEN is not set.\n"
                "    export PINTEREST_TOKEN='...' and re-run.\n"
                "    See tools/README-pinterest.md for how to get one.")
        print("\n  fetching boards…")
        boards = paged("/boards", token)
        pins_by_board = {}

    by_name = {b.get("name"): b for b in boards}
    missing = [n for n in BOARDS if n not in by_name]
    if missing:
        die("Could not find these boards on the account:\n      "
            + "\n      ".join(missing)
            + "\n\n    Boards visible to this token:\n      "
            + ("\n      ".join(sorted(n for n in by_name if n)) or "(none)")
            + "\n\n    Names must match exactly, middle dot and all. If the token is new, "
              "check it was issued for the business account that owns these boards.")

    d = read_data()
    cases = {c["id"]: c for c in d["cases"]}

    for board_name, case_id in BOARDS.items():
        if case_id not in cases:
            die(f"data.js has no case with id '{case_id}'. Add the case entry first.")
        board = by_name[board_name]
        print(f"\n  {board_name}  →  {case_id}")

        if args.dry_run:
            pins = pins_by_board.get(board["id"], [])
        else:
            pins = paged(f"/boards/{board['id']}/pins", token)
        print(f"    {len(pins)} pins")

        frames = sync_board(case_id, pins, verbose=True)
        if pins and not frames:
            # every download failed. Writing this through would silently empty the
            # section on the live site, which is worse than stopping here.
            die(f"'{board_name}' has {len(pins)} pins but not one image downloaded.\n"
                "    data.js has NOT been touched. Check the network and re-run.")
        cases[case_id]["frames"] = frames
        print(f"    → {len(frames)} frames written to frames/{case_id}/")

    write_data(d)
    total = sum(len(cases[c]["frames"]) for c in BOARDS.values())
    print(f"\n  ✓ data.js updated — {total} frames across {len(BOARDS)} boards")
    print("    Open map.html?s=moodboard to check the section.\n")


if __name__ == "__main__":
    main()
