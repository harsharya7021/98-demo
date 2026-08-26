#!/usr/bin/env python3
"""
pinterest_sync.py — pull the Ambrosia moodboard boards into The Work at build time.

Why build time and not runtime: this site is static HTML opened from a folder.
A runtime API call needs a server to hold the client secret and refresh the token
(Pinterest tokens expire), and Pinterest's own board widget paints its grid inside
an iframe we cannot restyle. So we call the API once from this machine, write the
images into frames/ and the metadata into data.js, and the site stays static.

Commands
--------
  python3 tools/pinterest_sync.py auth              one-time OAuth, writes .pinterest.json
  python3 tools/pinterest_sync.py boards            list boards + ids (sanity check)
  python3 tools/pinterest_sync.py sync              pull pins -> frames/ + data.js + case pages
  python3 tools/pinterest_sync.py sync --dry-run    show what would change, write nothing
  python3 tools/pinterest_sync.py relink            no API: register on-disk frames into data.js
  python3 tools/pinterest_sync.py sync --fixture F  no API: run from a saved JSON payload (testing)

Setup
-----
1. The Pinterest account must be a BUSINESS account. api v5 refuses personal ones.
2. developers.pinterest.com -> create an app -> note App ID and App secret.
3. Add  http://localhost:8723/callback  as a redirect URI on the app.
4. Request these scopes (the boards are SECRET, so the _secret variants are required
   — without them the boards return 404 and it looks like a wrong id):
       boards:read  boards:read_secret  pins:read  pins:read_secret
5. export PINTEREST_APP_ID=...  PINTEREST_APP_SECRET=...
6. python3 tools/pinterest_sync.py auth

Trial access is ~1000 requests/day, which is roughly 900 more than this needs.

Rights
------
These pins are other people's photographs. Every frame written here is logged in
frames/<case>/sources.json with its pin url and original source link. The moodboard
section is labelled "concepts, not delivered work" — keep it that way, and never let
a pinned reference migrate into a case-study grid where it reads as ours.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_JS = ROOT / "data.js"
FRAMES = ROOT / "frames"
CASES = ROOT / "cases"
TOKEN_FILE = ROOT / ".pinterest.json"          # gitignored — holds the refresh token

API = "https://api.pinterest.com/v5"
REDIRECT_URI = "http://localhost:8723/callback"
SCOPES = "boards:read,boards:read_secret,pins:read,pins:read_secret"

# Which Pinterest board feeds which case in the `moodboard` ("For Ambrosia") section.
# Board names are matched case-insensitively and punctuation-loosely, so "Ambrosia ·
# The Usual" and "ambrosia - the usual" both hit. If a case id does not exist yet it
# is scaffolded from TEMPLATE_CASE.
BOARDS = {
    "Ambrosia · The Usual": {
        "case": "amb-ritual",
        "max": 12,
    },
    "Ambrosia · Gifting": {
        "case": "amb-gift-mood",
        "max": 12,
        # only used if the case has to be created:
        "new": {
            "n": "The gifting register",
            "code": "AMB7",
            "k": "Gifting · reference board",
            "s": "The register the gifting campaign lives in: rigid cream boxes, satin "
                 "ribbon in burgundy, script wordmarks and wax seals, the stack carried "
                 "rather than the shelf photographed.",
            "m": "Mood reference",
            "stats": [["Register", "Cream · burgundy"]],
            "pull": None,
            "note": "Mood reference — other people's photography, gathered for direction.",
            "role": "Reference · mood",
            "did": [
                "Cream and burgundy as the whole system",
                "The box carried, handed over, opened",
            ],
        },
    },
}

TEMPLATE_CASE = "amb-ritual"   # case page cloned when scaffolding a new case
SECTION = "moodboard"

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def die(msg: str) -> "None":
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def norm(s: str) -> str:
    """Loose board-name key: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def image_size(path: Path) -> "tuple[int, int]":
    """Width/height for JPEG and PNG without pulling in Pillow."""
    with open(path, "rb") as fh:
        head = fh.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return int(w), int(h)
        if head[:2] == b"\xff\xd8":
            fh.seek(2)
            while True:
                b = fh.read(1)
                while b and b != b"\xff":
                    b = fh.read(1)
                marker = fh.read(1)
                while marker == b"\xff":
                    marker = fh.read(1)
                if not marker:
                    break
                m = marker[0]
                if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                    continue
                seg = fh.read(2)
                if len(seg) < 2:
                    break
                length = struct.unpack(">H", seg)[0]
                if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                    body = fh.read(5)
                    h, w = struct.unpack(">HH", body[1:5])
                    return int(w), int(h)
                fh.seek(length - 2, 1)
    raise ValueError(f"cannot read image dimensions from {path.name}")


def load_data() -> dict:
    src = DATA_JS.read_text(encoding="utf-8")
    return json.loads(src[src.index("{"):].rstrip().rstrip(";"))


def save_data(d: dict) -> None:
    """Writes data.js in exactly the shape it already has — verified byte-identical
    on a no-op round trip, so a diff only ever shows what we actually changed."""
    DATA_JS.write_text("window.WORK=" + json.dumps(d, ensure_ascii=False) + ";",
                       encoding="utf-8")


def case_by_id(d: dict, cid: str) -> "dict | None":
    return next((c for c in d["cases"] if c.get("id") == cid), None)


# --------------------------------------------------------------------------
# oauth
# --------------------------------------------------------------------------


def _app_creds() -> "tuple[str, str]":
    app_id = os.environ.get("PINTEREST_APP_ID")
    secret = os.environ.get("PINTEREST_APP_SECRET")
    if not app_id or not secret:
        die("set PINTEREST_APP_ID and PINTEREST_APP_SECRET in the environment")
    return app_id, secret


def _token_request(payload: dict) -> dict:
    app_id, secret = _app_creds()
    basic = base64.b64encode(f"{app_id}:{secret}".encode()).decode()
    req = urllib.request.Request(
        f"{API}/oauth/token",
        data=urllib.parse.urlencode(payload).encode(),
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        die(f"token request failed ({e.code}): {e.read().decode()[:400]}")


class _Callback(BaseHTTPRequestHandler):
    code = None

    def do_GET(self):  # noqa: N802
        q = urllib.parse.urlparse(self.path)
        if q.path != "/callback":
            self.send_response(404); self.end_headers(); return
        params = urllib.parse.parse_qs(q.query)
        _Callback.code = (params.get("code") or [None])[0]
        body = (b"<body style='font:16px/1.5 -apple-system,sans-serif;"
                b"background:#F4EFE8;color:#241A12;padding:60px'>"
                b"<b>Authorised.</b> Close this tab and return to the terminal.</body>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence
        pass


def cmd_auth(_args) -> None:
    app_id, _ = _app_creds()
    url = (f"https://www.pinterest.com/oauth/?client_id={app_id}"
           f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
           f"&response_type=code&scope={urllib.parse.quote(SCOPES)}")
    print("Opening Pinterest to authorise. If nothing opens, paste this:\n\n  " + url + "\n")
    webbrowser.open(url)

    srv = HTTPServer(("localhost", 8723), _Callback)
    srv.handle_request()
    srv.server_close()
    if not _Callback.code:
        die("no authorisation code came back — check the redirect URI on the app")

    tok = _token_request({
        "grant_type": "authorization_code",
        "code": _Callback.code,
        "redirect_uri": REDIRECT_URI,
    })
    TOKEN_FILE.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)
    print(f"saved {TOKEN_FILE.name}  (add it to .gitignore — it is a credential)")


def access_token() -> str:
    if not TOKEN_FILE.exists():
        die("no .pinterest.json — run:  python3 tools/pinterest_sync.py auth")
    tok = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    refresh = tok.get("refresh_token")
    if not refresh:
        die(".pinterest.json has no refresh_token — re-run auth")
    fresh = _token_request({"grant_type": "refresh_token", "refresh_token": refresh})
    fresh.setdefault("refresh_token", refresh)
    TOKEN_FILE.write_text(json.dumps(fresh, indent=2), encoding="utf-8")
    return fresh["access_token"]


# --------------------------------------------------------------------------
# api
# --------------------------------------------------------------------------


def api_get(path: str, token: str, **params) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        if e.code == 404:
            detail += ("\nhint: a secret board 404s unless the token carries "
                       "boards:read_secret and pins:read_secret")
        die(f"GET {path} failed ({e.code}): {detail}")


def paged(path: str, token: str, **params):
    bookmark = None
    while True:
        p = dict(params)
        if bookmark:
            p["bookmark"] = bookmark
        page = api_get(path, token, **p)
        for item in page.get("items", []):
            yield item
        bookmark = page.get("bookmark")
        if not bookmark:
            return


def list_boards(token: str) -> list:
    return list(paged("/boards", token, page_size=100, privacy="ALL"))


def cmd_boards(_args) -> None:
    token = access_token()
    for b in list_boards(token):
        print(f'{b["id"]:>22}  {b.get("privacy",""):<8} {b.get("pin_count","?"):>4} pins  {b["name"]}')


# --------------------------------------------------------------------------
# pin -> image
# --------------------------------------------------------------------------


def best_image(pin: dict) -> "tuple[str | None, str]":
    """Largest still available for a pin. Video pins fall back to their cover frame."""
    media = pin.get("media") or {}
    images = media.get("images") or {}
    best, best_w = None, -1
    for key, img in images.items():
        if not isinstance(img, dict) or not img.get("url"):
            continue
        w = img.get("width") or 0
        if not w:
            m = re.match(r"(\d+)x", key)
            w = int(m.group(1)) if m else 0
        if w > best_w:
            best, best_w = img["url"], w
    if best:
        return best, "image"
    cover = media.get("cover_image_url")
    if cover:
        return cover, "video-cover"
    return None, "none"


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "98-work-sync/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as fh:
        shutil.copyfileobj(r, fh)


# --------------------------------------------------------------------------
# writing into the site
# --------------------------------------------------------------------------


def scaffold_case(d: dict, cid: str, spec: dict) -> dict:
    """Clone the template case page and register a new case in the moodboard section."""
    tpl = case_by_id(d, TEMPLATE_CASE)
    if not tpl:
        die(f"template case {TEMPLATE_CASE} not found in data.js")

    page = f"cases/gen-{cid}_case_study.html"
    src = CASES / f"gen-{TEMPLATE_CASE}_case_study.html"
    dst = ROOT / page
    if src.exists() and not dst.exists():
        html = src.read_text(encoding="utf-8")
        html = html.replace(TEMPLATE_CASE, cid)
        html = html.replace(esc(tpl["n"]), esc(spec["n"])).replace(tpl["n"], spec["n"])
        if tpl.get("s"):
            html = html.replace(esc(tpl["s"]), esc(spec["s"])).replace(tpl["s"], spec["s"])
        if tpl.get("code"):
            html = html.replace(tpl["code"], spec["code"])

        # The "What we did" list and the note are the template's own copy — swap them
        # for this case's, or the new page quietly ships someone else's sentences.
        did = "".join(f"<li>{esc(x)}</li>" for x in spec.get("did") or [])
        html = re.sub(r'<ul class="dash">.*?</ul>',
                      f'<ul class="dash">{did}</ul>', html, count=1, flags=re.S)
        note_re = re.compile(
            r'<div class="label" style="margin-top:26px">Note</div><p>.*?</p>', re.S)
        if spec.get("note"):
            html = note_re.sub(
                '<div class="label" style="margin-top:26px">Note</div>'
                f'<p>{esc(spec["note"])}</p>', html, count=1)
        else:
            html = note_re.sub("", html, count=1)

        dst.write_text(html, encoding="utf-8")
        print(f"  scaffolded {page}")
        if spec.get("pull"):
            print("    note: the template carries no pull-quote block — add it by hand")

    case = {
        "id": cid, "n": spec["n"], "code": spec["code"], "sec": SECTION,
        "k": spec["k"], "s": spec["s"], "m": spec["m"], "stats": spec["stats"],
        "pull": spec.get("pull"), "cover": "", "note": spec.get("note"),
        "frames": [], "role": spec["role"], "did": spec["did"], "casepage": page,
    }
    d["cases"].append(case)
    return case


SLATS_RE = re.compile(r'(<div class="slats">)(.*?)(</div>)', re.S)


def rewrite_slats(case: dict) -> bool:
    """Rebuild the gallery strip on the case page from the case's frames list."""
    page = ROOT / (case.get("casepage") or "")
    if not page.exists():
        return False
    html = page.read_text(encoding="utf-8")
    if not SLATS_RE.search(html):
        return False
    figs = []
    for i, fr in enumerate(case["frames"], 1):
        figs.append(
            f'<figure class="slat"><img src="../frames/{case["id"]}/{fr["f"]}" '
            f'alt="{esc(case["n"])} — frame {i}" loading="lazy">'
            f'<figcaption><b>{i:02d}</b> &nbsp;{esc(case["n"])}</figcaption></figure>'
        )
    new = SLATS_RE.sub(lambda m: m.group(1) + "".join(figs) + m.group(3), html, count=1)
    if new != html:
        page.write_text(new, encoding="utf-8")
        return True
    return False


def register_frames(case: dict, files: "list[str]") -> None:
    """Point the case at these files, in order, with real pixel dimensions."""
    frames = []
    for name in files:
        p = FRAMES / case["id"] / name
        try:
            w, h = image_size(p)
        except Exception as exc:  # keep going; a bad file should not kill the run
            print(f"  ! {p.name}: {exc}")
            continue
        frames.append({"f": name, "w": w, "h": h})
    case["frames"] = frames


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def cmd_sync(args) -> None:
    d = load_data()

    if args.fixture:
        payload = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        token = None
    else:
        token = access_token()
        boards = {norm(b["name"]): b for b in list_boards(token)}
        payload = {}
        for name in BOARDS:
            b = boards.get(norm(name))
            if not b:
                print(f"  ! board not found on the account: {name}")
                continue
            payload[name] = list(paged(f'/boards/{b["id"]}/pins', token, page_size=100))
            print(f'  {name}: {len(payload[name])} pins  (board {b["id"]})')

    touched = []
    for name, cfg in BOARDS.items():
        pins = payload.get(name)
        if not pins:
            continue
        cid = cfg["case"]
        case = case_by_id(d, cid)
        if case is None:
            if args.dry_run:
                print(f"  would scaffold case {cid}")
                continue
            case = scaffold_case(d, cid, cfg["new"])

        outdir = FRAMES / cid
        pins = pins[: cfg.get("max") or len(pins)]

        if args.dry_run:
            print(f"  {name} -> {cid}: {len(pins)} frames into {outdir.relative_to(ROOT)}")
            continue

        outdir.mkdir(parents=True, exist_ok=True)
        # Reference frames are fully rebuilt each run so removing a pin removes the
        # frame. Only files this script owns (NN.jpg + sources.json) are cleared.
        for old in outdir.glob("*.jpg"):
            old.unlink()
        (outdir / "sources.json").unlink(missing_ok=True)

        written, sources = [], []
        for i, pin in enumerate(pins, 1):
            url, kind = best_image(pin)
            if not url:
                print(f"  ! pin {pin.get('id')} has no usable image, skipped")
                continue
            name_ = f"{i:02d}.jpg"
            try:
                download(url, outdir / name_)
            except Exception as exc:
                print(f"  ! {name_}: {exc}")
                continue
            written.append(name_)
            sources.append({
                "file": name_,
                "kind": kind,
                "pin": f"https://www.pinterest.com/pin/{pin.get('id')}/",
                "link": pin.get("link"),
                "title": pin.get("title") or "",
                "alt": pin.get("alt_text") or "",
            })

        register_frames(case, written)
        (outdir / "sources.json").write_text(
            json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
        rewrote = rewrite_slats(case)
        touched.append(f'{cid}: {len(case["frames"])} frames'
                       + ("  + case page" if rewrote else ""))

    if args.dry_run:
        print("dry run — nothing written")
        return

    # Section hero strip: two frames, one from each campaign, so the section card
    # reads as a pair rather than as whichever board synced last.
    heroes = []
    for cfg in BOARDS.values():
        c = case_by_id(d, cfg["case"])
        if c and c["frames"]:
            heroes.append(f'frames/{c["id"]}/{c["frames"][0]["f"]}')
    if heroes:
        d.setdefault("heroes", {})[SECTION] = heroes

    save_data(d)
    for line in touched:
        print("  " + line)
    print(f"wrote {DATA_JS.name}")


def cmd_relink(args) -> None:
    """No API. Registers images already sitting in frames/<case>/ into data.js.

    The moodboard cases shipped out of sync — amb-static, amb-ritual, amb-props and
    amb-trunk all have images on disk that data.js does not list, so those frames
    never render. This reconciles them.
    """
    d = load_data()
    changed = []
    for case in d["cases"]:
        if case.get("sec") != SECTION:
            continue
        outdir = FRAMES / case["id"]
        if not outdir.is_dir():
            continue
        files = sorted(p.name for p in outdir.glob("*.jpg"))
        before = [f["f"] for f in case.get("frames") or []]
        if files == before:
            continue
        if args.dry_run:
            print(f'  {case["id"]}: {before or "[]"} -> {files}')
            changed.append(case["id"])
            continue
        register_frames(case, files)
        rewrite_slats(case)
        changed.append(f'{case["id"]}: {len(before)} -> {len(case["frames"])} frames')

    if not changed:
        print("nothing to relink — data.js already matches the frames on disk")
        return
    if args.dry_run:
        print("dry run — nothing written")
        return
    save_data(d)
    for line in changed:
        print("  " + line)
    print(f"wrote {DATA_JS.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth", help="one-time OAuth").set_defaults(fn=cmd_auth)
    sub.add_parser("boards", help="list boards and ids").set_defaults(fn=cmd_boards)

    s = sub.add_parser("sync", help="pull pins into frames/ and data.js")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--fixture", help="read pins from a JSON file instead of the API")
    s.set_defaults(fn=cmd_sync)

    r = sub.add_parser("relink", help="register on-disk frames into data.js")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_relink)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
