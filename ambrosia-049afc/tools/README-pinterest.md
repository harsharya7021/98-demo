# Getting the two moodboards onto The Work

> ## ⚡ Use `fetch-boards.py`. The API route is blocked.
>
> ```bash
> cd "…/Ambrosia — The Work (site)"
> python3 tools/fetch-boards.py --check   # verify the 32 URLs resolve
> python3 tools/fetch-boards.py           # download + wire into data.js
> ```
>
> No token, no app, no approval. Both boards are public, so their images are
> ordinary public URLs; `tools/boards-manifest.json` already holds all 32,
> harvested 26 Aug 2026.
>
> **Why not the API:** app 1604984 returns `401 code 3 — "Your application
> consumer type is not supported"` on *every* v5 endpoint. That is Pinterest's
> signal that trial access was never activated on the app. The Generate-token
> button still issues tokens; they are inert. Nothing on our side fixes it.
>
> **If the boards change,** the manifest goes stale — `--check` will tell you
> (Pinterest rotates CDN URLs). Re-harvest before re-running.
>
> Everything below is the API route, kept for when the app is finally approved.

---


The site stays static. This runs **once on your Mac**, pulls the boards down, and
writes them into `data.js` and `frames/` like any other case. Nothing Pinterest
ships ever executes on the page.

Takes about ten minutes, most of it waiting for Pinterest to approve the app.

---

## Before you start

The account is already right: `harsharya7021` was converted in place to a
business account (**Ninety-Eight Entertainment**, linked to ninety-eight.in), and
both boards survived the conversion —

| Board | Pins |
|---|---|
| Ambrosia · The Usual | 13 |
| Ambrosia · Gifting | 19 |

Both are still **private**, which is fine. The API reads your own private boards;
it's only the embed widget that can't.

---

## 1 · Register the app

The form at **developers.pinterest.com → Connect app** is already filled in and
sitting in an open tab. Two things it needs from you before Submit:

- **App icon** (required — it rejected the earlier `98 DP.png`). Click Upload and
  choose `tools/app-icon/98-appicon-ink-512.png`. The paper version is beside it
  if you'd rather.
- **The privacy URL must resolve first.** Pinterest's reviewer opens that link,
  and a dead one fails the submission — which is what happened on 26 Aug.

  The page is now in the **actual deployed repo**:
  `Brand HQ/Design Source (heavy)/98-Figma-Brief/website-v2/`, as both
  `privacy.html` and `privacy/index.html`. Ship it the usual way:

  ```bash
  cd "~/Library/Mobile Documents/com~apple~CloudDocs/98 Entertainment/Brand HQ/Design Source (heavy)/98-Figma-Brief/website-v2"
  git add privacy.html privacy/
  git commit -m "add privacy policy"
  git push
  ```

  Vercel rebuilds on push; `ninety-eight.in/privacy` is live in ~30 seconds.
  Confirm it loads, then resubmit the app.

  While you're in `index.html`, add a footer link to `/privacy` — right now the
  live site has no privacy link anywhere in it, which is both a reviewer flag and
  just a gap. I couldn't make that edit: the repo is iCloud-evicted, so the
  sandbox can't read `index.html` to patch it.

Everything else is done: purpose set to *Personal API access (single, personal
use)*, use case *Reporting*, audience *Businesses*, and **Reads Pins/Boards →
"Yes, mine"**. That combination is the cheapest thing for Pinterest to approve,
because it asks for nothing involving other people's data.

Then submit for **Trial access**.

Scopes needed — read-only, nothing else:

```
boards:read
pins:read
```

## 2 · Generate a token

Trial access lets you generate a token straight from the console — **no OAuth
flow to build**. In your app's page, generate a test token with the two scopes
above.

> ⚠️ Test tokens **expire after 24 hours**. That's fine: this is a build-time
> job. Generate one, run the sync, let it expire. If you re-run next month,
> generate a fresh one then.

## 3 · Run the sync

In Terminal, from the site folder:

```bash
cd "~/Library/Mobile Documents/com~apple~CloudDocs/98 Entertainment/Pitches & Prospects/Ambrosia/Strategy & Decks/Ambrosia — The Work (site)"

export PINTEREST_TOKEN='paste-the-token-here'
python3 tools/pinterest-sync.py
```

**Keep the token in that shell and nowhere else.** Don't put it in a file in this
folder, don't commit it, and don't paste it into a chat — including to me. The
script only ever reads it from the environment, so I never need to see it.

You should get something like:

```
  Ambrosia · The Usual  →  amb-board-usual
    13 pins
      · 01.jpg  1000×1500  kinfolk.com
      ...
    → 13 frames written to frames/amb-board-usual/

  ✓ data.js updated — 32 frames across 2 boards
```

Then open `map.html?s=moodboard` and click through to either board.

## 4 · If something goes wrong

| What you see | What it means |
|---|---|
| `PINTEREST_TOKEN is not set` | The `export` didn't take, or you opened a new tab. Re-export in the same shell. |
| `401` | Token expired (they last 24h) or got truncated on paste. Generate a fresh one. |
| `403` | The app is missing `boards:read` / `pins:read`. Add the scopes and regenerate. |
| `429` | Trial access is ~1,000 requests/day. Wait for the window and re-run. |
| `Could not find these boards` | The script matches board names **exactly**, middle dot and all. It prints every board it can see — compare against `BOARDS` at the top of the script. |
| `N pins but not one image downloaded` | Network died mid-run. `data.js` is deliberately left untouched rather than emptied. Just re-run. |

## What it actually does

1. Lists your boards, matches the two by name.
2. Lists each board's pins, takes the largest image on each.
3. Downloads them to `frames/amb-board-usual/` and `frames/amb-board-gifting/`,
   numbered `01.jpg`, `02.jpg`…
4. Rewrites **only** the `frames` array of those two cases in `data.js`. Every
   other case is left byte-identical — verified, not assumed.
5. Writes `sources.json` next to the images: pin link, source domain, per frame.

Re-running rebuilds both folders from scratch, so the site matches whatever the
boards hold that day. Running it twice in a row produces a byte-identical
`data.js`.

## Two things to keep honest

**These are other people's photographs.** Pinning them on Pinterest carries
attribution and a link back; re-hosting them on our own site does not. That's why
`sources.json` exists and why both cases carry a note saying they're reference,
not delivered work. Don't let these frames drift into a case-study grid where
they'd read as ours.

**Nothing here is client-facing proof.** The section is called *For Ambrosia* and
its own description already says "concepts, not delivered work". Keep it that way.

---

## ⚠️ There is a second sync script in this folder

`tools/pinterest_sync.py` (underscore) is **not mine** — it predates my work here,
dated 25 Aug 16:59, with a compiled `.pyc` beside it, so it has been run at least
once. It's an iCloud placeholder I couldn't materialise, so I have never read a
line of it and don't know what it does.

Mine is `tools/pinterest-sync.py` (**hyphen**).

Both would write to `data.js`. Before running either, work out which one you
want and delete the other — two scripts rewriting the same file is how the
moodboard section ends up scrambled.
