/* ─────────────────────────────────────────────────────────────────────────────
   harvest-boards.js — rebuild tools/boards-manifest.json yourself, in 60 seconds.

   You'll need this every time pins are added or removed. It needs a real logged-in
   browser: Pinterest's grid is virtualised (it won't render in a background tab),
   its internal API refuses synthetic calls, the v5 API is dead on our app, and the
   RSS feed no longer exists. A rendered page is the only source left.

   HOW TO RUN
   1. Open  https://www.pinterest.com/harsharya7021/ambrosia-the-usual/
      Keep the window in front — a background tab will not render the pins.
   2. Open the console:  ⌥⌘J
   3. Paste this whole file, hit Return. It scrolls the board and collects.
   4. Do the same on  .../ambrosia-gifting/
   5. After the SECOND board it copies the finished manifest to your clipboard
      and prints ✓ COPIED. Paste it over tools/boards-manifest.json.
   6. python3 tools/fetch-boards.py --check   then   python3 tools/fetch-boards.py

   Order doesn't matter. Re-running a board just replaces that board's entry.
   It keeps partial progress in localStorage, so you can do them minutes apart.
   ───────────────────────────────────────────────────────────────────────────── */

(async () => {
  const KEY = 'ninetyEightBoardHarvest';
  const BOARDS = {
    'ambrosia-the-usual': { name: 'Ambrosia · The Usual', case: 'amb-board-usual' },
    'ambrosia-gifting':   { name: 'Ambrosia · Gifting',   case: 'amb-board-gifting' },
  };

  const slug = location.pathname.replace(/\/+$/, '').split('/').pop();
  const meta = BOARDS[slug];
  if (!meta) {
    console.error('✗ Not on one of the two boards. Open ambrosia-the-usual or ambrosia-gifting first.');
    return;
  }
  if (document.visibilityState !== 'visible') {
    console.warn('⚠ This tab is in the background. Pinterest will not render the pins — bring the window to the front and re-run.');
  }

  // Largest image Pinterest offers for a pin. srcset lists the sizes; /originals/
  // is the untouched upload, which is what we want on a retina page.
  const best = (img) => {
    let url = img.currentSrc || img.src || '';
    const ss = img.getAttribute('srcset') || '';
    if (ss) {
      let w = -1;
      ss.split(',').forEach(p => {
        const [u, d] = p.trim().split(/\s+/);
        const n = parseFloat(d) || 1;
        if (n > w) { w = n; url = u; }
      });
    }
    return url.replace(/\/\d+x\//, '/originals/');
  };

  const found = new Map();
  const harvest = () => {
    document.querySelectorAll('a[href*="/pin/"]').forEach(a => {
      const m = a.getAttribute('href').match(/\/pin\/(\d+)/);
      if (!m) return;
      const img = a.querySelector('img');
      if (!img) return;
      const u = best(img);
      if (!u || !/pinimg/.test(u)) return;
      if (!found.has(m[1])) found.set(m[1], u);
    });
  };

  const expected = (document.body.innerText.match(/(\d+)\s*Pins/) || [])[1];
  console.log(`⟳ harvesting "${meta.name}"${expected ? ` — board says ${expected} pins` : ''}…`);

  window.scrollTo(0, 0);
  await new Promise(r => setTimeout(r, 1200));
  let last = -1, same = 0;
  for (let i = 0; i < 120 && same < 7; i++) {
    harvest();
    window.scrollBy(0, Math.round(innerHeight * 0.7));
    await new Promise(r => setTimeout(r, 550));
    if (found.size === last) same++; else { same = 0; last = found.size; }
    if (scrollY + innerHeight >= document.body.scrollHeight - 5) {
      harvest();
      await new Promise(r => setTimeout(r, 900));
      harvest();
    }
  }
  harvest();
  window.scrollTo(0, 0);

  if (expected && found.size !== +expected) {
    console.warn(`⚠ collected ${found.size} but the board says ${expected}. Scroll to the bottom by hand and re-run before trusting this.`);
  }

  const store = JSON.parse(localStorage.getItem(KEY) || '{}');
  store[slug] = {
    name: meta.name,
    case: meta.case,
    pins: [...found].map(([id, url]) => ({
      pin: id,
      pin_url: `https://www.pinterest.com/pin/${id}/`,
      image: url,
    })),
  };
  localStorage.setItem(KEY, JSON.stringify(store));
  console.log(`✓ ${meta.name}: ${found.size} pins`);

  const order = ['ambrosia-the-usual', 'ambrosia-gifting'];
  const missing = order.filter(s => !store[s]);
  if (missing.length) {
    console.log(`→ now do the other board: https://www.pinterest.com/harsharya7021/${missing[0]}/`);
    return;
  }

  const manifest = {
    _note: `Harvested ${new Date().toISOString().slice(0, 10)} from the two PUBLIC boards ` +
           `in a logged-in browser, via tools/harvest-boards.js. Images are other ` +
           `people's photographs — see the note on each case in data.js.`,
    boards: order.map(s => store[s]),
  };
  const out = JSON.stringify(manifest, null, 2);

  try {
    await navigator.clipboard.writeText(out);
    const total = manifest.boards.reduce((n, b) => n + b.pins.length, 0);
    console.log(`✓ COPIED — ${total} pins across both boards.`);
    console.log('  Paste over tools/boards-manifest.json, then:');
    console.log('  python3 tools/fetch-boards.py --check && python3 tools/fetch-boards.py');
    localStorage.removeItem(KEY);
  } catch (e) {
    console.warn('Clipboard blocked (click the page once, then re-run). Manifest below — copy it by hand:');
    console.log(out);
  }
})();
