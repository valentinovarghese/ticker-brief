#!/usr/bin/env python3
"""
Build site.html from every edition in editions/.

Each edition is one JSON file named YYYY-MM-DD.json. The newest renders in
full at the top; every older one is kept below in a collapsed block. Nothing
is ever dropped — the repo is the archive, so history is lossless and the
page is a pure function of the files on disk.

Usage:  python3 build.py            # writes site.html and index.html
        python3 build.py --check    # validate editions, write nothing

index.html is a byte-identical copy of site.html, written so GitHub Pages
can serve the archive at a public URL. site.html remains the file the
Artifact tool publishes.

Edition text may contain inline <b>/<em> markup and HTML entities; it is
authored by the brief itself, not user input, so it is emitted verbatim.
"""

import base64
import hashlib
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
EDITIONS = ROOT / "editions"
OUT = ROOT / "site.html"
# GitHub Pages serves index.html; site.html is what the Artifact tool
# publishes. Both hold identical bytes so the two stay in step.
PAGES_OUT = ROOT / "index.html"

REQUIRED = ("date", "headline", "quick", "entries")

# House style: no em dashes anywhere in the rendered page. Editions are
# written by a language model, which reaches for them constantly, so the
# rule is enforced here at build time rather than trusted to the writing.
# A spaced em dash almost always sits where a comma belongs; an unspaced
# one is doing the same job without the spaces. Ranges keep their en dash,
# which is correct typography and not the tell being avoided.
DASHES = (
    (" &mdash; ", ", "), ("&mdash; ", ", "), (" &mdash;", ", "), ("&mdash;", ", "),
    (" — ", ", "), ("— ", ", "), (" —", ", "), ("—", ", "),
)


def dedash(text):
    for old, new in DASHES:
        text = text.replace(old, new)
    # Tidy the seams a substitution can leave behind.
    for bad, good in ((" ,", ","), (",,", ","), (", .", "."), (", ,", ","),
                      (", :", ":"), ("(, ", "("), (", )", ")")):
        text = text.replace(bad, good)
    return text


# Editions are drafted from web search results, so their text is not fully
# trusted: a page the routine reads could carry markup that ends up copied
# into an edition and rendered verbatim on a public site. Inline emphasis is
# the only markup the brief ever needs, so everything else is escaped rather
# than executed. Entities are left intact, since the editions rely on them.
ALLOWED_TAG = r"</?(?:b|i|em|strong|u|br)\s*/?>"
ENTITY = r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});"
KEEP = re.compile(f"({ALLOWED_TAG}|{ENTITY})")


def safe_html(text):
    parts = KEEP.split(text)
    out = []
    for i, part in enumerate(parts):
        if not part:
            continue
        # Odd indices are the captured tags and entities, kept as authored.
        # quote=True so a string landing inside an attribute (an href, a
        # class) cannot close the quote and smuggle in an attribute of its
        # own; in text content &quot; still renders as a plain quote mark.
        out.append(part if i % 2 else html.escape(part, quote=True))
    return "".join(out)


def scrub(node):
    """Walk a decoded JSON tree, de-dashing and sanitising every string."""
    if isinstance(node, str):
        return safe_html(dedash(node))
    if isinstance(node, list):
        return [scrub(v) for v in node]
    if isinstance(node, dict):
        return {k: scrub(v) for k, v in node.items()}
    return node


# ---------------------------------------------------------------- loading

def load_editions():
    """Newest first. Skips nothing silently — bad files raise."""
    files = sorted(EDITIONS.glob("*.json"), reverse=True)
    if not files:
        sys.exit("no editions found in editions/ — nothing to build")

    out = []
    for f in files:
        try:
            ed = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            sys.exit(f"{f.name} is not valid JSON: {e}")
        missing = [k for k in REQUIRED if k not in ed]
        if missing:
            sys.exit(f"{f.name} is missing required keys: {', '.join(missing)}")
        out.append(scrub(ed))
    return out


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def pretty_date(iso):
    y, m, d = (int(p) for p in iso.split("-"))
    dt = date(y, m, d)
    return f"{DAYS[dt.weekday()]} {dt.day} {MONTHS[dt.month - 1]} {dt.year}"


def short_date(iso):
    y, m, d = (int(p) for p in iso.split("-"))
    return f"{d} {MONTHS[m - 1]}"


def short_move(move):
    """Just the percentage, if there is one.

    Entry moves range from '+16.6% &middot; best day since 2008' to
    'reports after close'. The index is a price trail, so keep the number
    and drop both the commentary and the non-numeric placeholders.
    """
    head = move.split("&middot;")[0]
    return next((w for w in head.split() if "%" in w), "")


# ---------------------------------------------------------------- sections

def render_gauge(ed):
    bits = [f'<span>{pretty_date(ed["date"])}</span>']
    for g in ed.get("gauge", []):
        cls = ' class="gauge"' if g.get("tone") == "up" else ""
        bits.append(f'<span{cls}>{g["text"]}</span>')
    return f'<div class="dateline">{"".join(bits)}</div>'


def render_quick(ed):
    # The <span> matters: the li is a grid, so every inline child (<b>, <em>)
    # would otherwise become its own grid item and break across cells.
    items = "".join(f"<li><span>{q}</span></li>" for q in ed["quick"])
    return ('<section class="band reveal"><h2>The 30-second version</h2>'
            f'<ol class="quick">{items}</ol></section>')


def render_macro(ed):
    rows = ed.get("macro") or []
    if not rows:
        return ""
    body = "".join(
        f'<dt>{m["dt"]}</dt>'
        f'<dd><span class="lead">{m.get("lead", "Why it matters")}</span>{m["dd"]}</dd>'
        for m in rows
    )
    return ('<section class="band reveal"><h2>Market-wide</h2>'
            f'<dl class="macro">{body}</dl></section>')


def render_note(note):
    return (f'<div class="note"><h3>{note["title"]}</h3>'
            f'<p>{note["body"]}</p></div>')


def render_entry(e):
    # The strength label sits under the headline sentence, not as a badge
    # stacked above it: a chip over the first line of body text reads as
    # template furniture and pushes the sentence down the card.
    head = [
        f'<span class="tick {e["dir"]}">'
        f'<span class="arrow">{ {"up": "&#9650;", "down": "&#9660;"}.get(e["dir"], "&#9679;") }</span> '
        f'{e["ticker"]}</span>',
    ]
    if e.get("move"):
        tone = e.get("move_tone", "flat")
        head.append(f'<span class="move {tone}">{e["move"]}</span>')

    parts = [f'<div class="entry-head">{"".join(head)}</div>',
             f'<p class="happened">{e["happened"]}</p>',
             f'<p class="grade {e["strength"]}">{e["strength_label"]}</p>']

    if e.get("figures"):
        parts.append(f'<p class="figures">{"<br>".join(e["figures"])}</p>')

    parts.append(f'<p class="why"><span class="lead">Why it matters</span>{e["why"]}</p>')

    foot = []
    for f in e.get("foot", []):
        cls = "flag" if f.get("flag") else ""
        foot.append(f'<div class="{cls}"><span class="k">{f["k"]}</span>{f["v"]}</div>')
    if foot:
        parts.append(f'<div class="footline">{"".join(foot)}</div>')

    html = f'<article class="entry">{"".join(parts)}</article>'
    if e.get("note_after"):
        html += render_note(e["note_after"])
    return html


def render_entries(ed):
    body = "".join(render_entry(e) for e in ed["entries"])
    return ('<section class="band reveal"><h2>Items &middot; sorted by size</h2>'
            f'<div class="entries">{body}</div></section>')


def render_readthrough(ed):
    rt = ed.get("readthrough")
    return ('<section class="band reveal"><h2>Read-through</h2>'
            f'{render_note(rt)}</section>') if rt else ""


def render_nothing(ed):
    nm = ed.get("nothing_material")
    if not nm or not nm.get("tickers"):
        return ""
    tickers = " &middot; ".join(nm["tickers"])
    out = (f'<section class="band reveal"><h2>Nothing material</h2>'
           f'<p class="quiet"><b>{tickers}</b>, no company-specific '
           f'events in the past 24 hours.</p>')
    if nm.get("note"):
        out += render_note(nm["note"])
    return out + "</section>"


def render_earnings(ed):
    rows = ed.get("earnings_ahead") or []
    if not rows:
        return ""
    items = "".join(
        f'<li><span class="d">{r["when"]}</span><span>{r["what"]}</span></li>'
        for r in rows
    )
    return ('<section class="band reveal"><h2>Earnings within 14 days</h2>'
            f'<ul class="dates">{items}</ul></section>')


def render_body(ed):
    """Everything below the masthead, shared by latest and archived days."""
    return "".join([
        render_quick(ed),
        render_macro(ed),
        render_entries(ed),
        render_readthrough(ed),
        render_nothing(ed),
        render_earnings(ed),
    ])


def render_ticker_index(editions):
    """One row per ticker, one chip per day it appeared, newest first.

    Pointless with a single edition on file, so it only appears once there
    is something to compare against.
    """
    if len(editions) < 2:
        return ""

    trails = {}
    for ed in editions:
        for e in ed["entries"]:
            trails.setdefault(e["ticker"], []).append(
                (ed["date"], e.get("dir", "flat"), e.get("move", ""))
            )

    rows = []
    for ticker in sorted(trails):
        chips = []
        for iso, direction, move in trails[ticker]:
            mv = short_move(move)
            chips.append(
                f'<span class="chip {direction}">{short_date(iso)}'
                + (f"<i>{mv}</i>" if mv else "")
                + "</span>"
            )
        rows.append(f'<div class="trow"><span class="tname {trails[ticker][0][1]}">'
                    f'{ticker}</span><span class="chips">{"".join(chips)}</span></div>')

    return ('<section class="band reveal"><h2>By ticker &middot; every day on file</h2>'
            f'<div class="tindex">{"".join(rows)}</div></section>')


def render_archive(older):
    if not older:
        return ('<section class="band reveal"><h2>Previous days</h2>'
                '<p class="empty">This is the first edition. Every future '
                'brief is kept here in full.</p></section>')

    blocks = []
    for ed in older:
        movers = ", ".join(
            e["ticker"] for e in ed["entries"]
            if e["strength"] in ("major", "notable")
        ) or "quiet day"
        blocks.append(
            f'<details class="day"><summary>'
            f'<span class="d">{pretty_date(ed["date"])}</span>'
            f'<span class="sum">{movers}</span></summary>'
            f'<div class="archive-body">{render_body(ed)}</div></details>'
        )
    return (f'<section class="band reveal"><h2>Previous days &middot; {len(older)} '
            f'archived</h2>{"".join(blocks)}</section>')


# ---------------------------------------------------------------- about

ABOUT = ROOT / "about.json"


def load_about():
    """Optional. Edit about.json to change the bio — no code change needed."""
    if not ABOUT.exists():
        return None
    try:
        return scrub(json.loads(ABOUT.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        sys.exit(f"about.json is not valid JSON: {e}")


def render_about(about):
    if not about:
        return ""
    paras = "".join(f"<p>{p}</p>" for p in about.get("paragraphs", []))
    # Only web URLs become links. Anything else (javascript:, data:, a bare
    # path) is refused loudly at build time rather than published quietly.
    for l in about.get("links", []):
        if not l["href"].startswith(("https://", "http://")):
            sys.exit(f'about.json link "{l.get("label", "?")}" is not an '
                     f'http(s) URL: {l["href"]!r}')
    links = "".join(
        f'<a class="pill" href="{l["href"]}" target="_blank" '
        f'rel="noopener noreferrer">{l["label"]}</a>'
        for l in about.get("links", [])
    )
    return (
        '<section class="band about reveal"><h2>About</h2>'
        '<div class="card">'
        '<div class="who">'
        f'<span class="mono-badge" aria-hidden="true">{about.get("monogram", "")}</span>'
        f'<span class="who-t"><b>{about.get("name", "")}</b>'
        f'<i>{about.get("role", "")}</i></span>'
        "</div>"
        f'<div class="bio">{paras}</div>'
        f'<div class="pills">{links}</div>'
        "</div></section>"
    )


# ---------------------------------------------------------------- page

# The one line that must run before first paint: it marks that JS is alive,
# which is what allows the reveal animations to hide anything at all.
HEAD_JS = 'document.documentElement.classList.add("js")'


def sha256_src(source):
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def csp():
    """A strict page policy, enforced by the browser itself.

    Escaping (safe_html) is the first line of defence; this is the second.
    Scripts and styles are allowed by hash of their exact source, so even
    if untrusted markup ever slipped past the sanitiser, an injected
    <script> or external load would still refuse to run. The hashes are
    computed from the same constants the page is rendered from, so they
    can never drift out of step with the content they allow.
    """
    return (
        "default-src 'none'; "
        f"script-src '{sha256_src(HEAD_JS)}' '{sha256_src(JS)}'; "
        f"style-src '{sha256_src(CSS)}'; "
        "img-src 'self' data:; "
        "base-uri 'none'; form-action 'none'"
    )


def render_page(editions):
    latest, older = editions[0], editions[1:]
    return PAGE.format(
        css=CSS,
        js=JS,
        head_js=HEAD_JS,
        csp=csp(),
        dateline=render_gauge(latest),
        headline=latest["headline"],
        body=render_body(latest),
        tindex=render_ticker_index(editions),
        archive=render_archive(older),
        about=render_about(load_about()),
        count=len(editions),
    )


def main():
    editions = load_editions()
    if "--check" in sys.argv:
        print(f"ok — {len(editions)} edition(s), newest {editions[0]['date']}")
        return
    page = render_page(editions)
    OUT.write_text(page, encoding="utf-8")
    PAGES_OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.name} and {PAGES_OUT.name} — {len(editions)} edition(s), "
          f"newest {editions[0]['date']}")


# ---------------------------------------------------------------- templates


CSS = """
  /* One visual world, deliberately: white paper, ink, and colour reserved
     for market direction. Nothing here is tinted blue, because a blue-grey
     neutral is the default every generated page arrives in. The neutrals
     carry a faint warm bias instead, so white reads as paper and not as
     an unpainted surface. */
  :root {
    --paper:#FFFFFF;
    --wash:#FAFAF8;
    --ink:#0C0D0E;
    --ink-2:#4C5157;
    --ink-3:#6E747B;
    --line:#E7E6E1;
    --line-2:#F0EFEB;
    --up:#046A44;
    --down:#B33124;
    --amber:#8A6D1F;
    --amber-wash:#FCFAF1;

    /* Prose reads in a serif, structure and data in sans and mono. The
       split is not decoration: it marks reported fact apart from the
       sentence that interprets it. */
    --prose:Charter,"Bitstream Charter","Source Serif 4",Cambria,Georgia,serif;
    --ui:system-ui,-apple-system,"Segoe UI Variable Text","Segoe UI",Roboto,
         Helvetica,Arial,sans-serif;
    --mono:ui-monospace,SFMono-Regular,"SF Mono","Cascadia Mono",Menlo,
           Consolas,monospace;

    --col:43rem;
    --ease:cubic-bezier(.22,.68,.28,1);
  }

  * { box-sizing:border-box; }
  html { scroll-behavior:smooth; color-scheme:light; background:var(--paper); }
  body { background:var(--paper); color:var(--ink); font-family:var(--prose);
         font-size:18px; line-height:1.65; margin:0;
         -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }

  /* ---- fixed chrome ---- */
  .progress { position:fixed; inset:0 auto auto 0; height:2px; width:100%;
              transform:scaleX(0); transform-origin:0 50%; z-index:60;
              background:var(--ink); transition:transform .08s linear;
              pointer-events:none; }
  .topbar { position:fixed; top:0; left:0; right:0; z-index:50;
            display:flex; align-items:center; gap:.85rem;
            padding:.7rem max(1.5rem,calc(50vw - var(--col)/2));
            background:rgba(255,255,255,.86); border-bottom:1px solid transparent;
            transform:translateY(-102%); opacity:0;
            transition:transform .4s var(--ease), opacity .3s var(--ease),
                       border-color .3s var(--ease); }
  @supports (backdrop-filter: blur(1px)) {
    .topbar { backdrop-filter:saturate(1.4) blur(14px); }
  }
  .topbar.show { transform:translateY(0); opacity:1; border-bottom-color:var(--line); }
  .tb-mark { font-family:var(--ui); font-size:.7rem; font-weight:660;
             letter-spacing:.02em; color:var(--ink); }
  .tb-date { font-family:var(--mono); font-size:.68rem; color:var(--ink-3);
             margin-left:auto; white-space:nowrap; }

  .wrap { max-width:var(--col); margin:0 auto; padding:5rem 1.5rem 7rem;
          display:flex; flex-direction:column; gap:3.5rem; }

  /* ---- masthead: the one loud thing on the page ---- */
  .masthead { display:flex; flex-direction:column; gap:1.5rem;
              padding-bottom:2.25rem; border-bottom:1px solid var(--ink); }
  .brandrow { display:flex; align-items:center; justify-content:space-between;
              gap:1rem; flex-wrap:wrap; }
  .wordmark { font-family:var(--ui); font-size:.7rem; font-weight:660;
              letter-spacing:.01em; color:var(--paper); background:var(--ink);
              padding:.34rem .6rem; border-radius:5px; }
  .social { font-family:var(--ui); font-size:.72rem; font-weight:560;
            color:var(--ink-2); text-decoration:none;
            display:inline-flex; align-items:center; gap:.42rem;
            border:1px solid var(--line); border-radius:7px;
            padding:.36rem .7rem; white-space:nowrap;
            transition:color .22s var(--ease), border-color .22s var(--ease),
                       background .22s var(--ease); }
  .social:hover { color:var(--ink); border-color:var(--ink); background:var(--wash); }
  .social svg { width:.9em; height:.9em; fill:currentColor; }
  .masthead h1 { font-family:var(--ui); font-size:clamp(1.6rem,3.9vw,2.2rem);
                 line-height:1.2; font-weight:620; letter-spacing:-.022em;
                 text-wrap:balance; margin:0; }
  .dateline { font-family:var(--mono); font-size:.72rem; color:var(--ink-3);
              display:flex; flex-wrap:wrap; gap:.4rem .95rem;
              font-variant-numeric:tabular-nums; }
  .dateline .gauge { color:var(--up); }

  /* ---- section shell ---- */
  .band { display:flex; flex-direction:column; gap:1.15rem; }
  .band > h2 { font-family:var(--ui); font-size:.7rem; font-weight:660;
               letter-spacing:.09em; text-transform:uppercase; color:var(--ink);
               margin:0; padding-bottom:.65rem; border-bottom:1px solid var(--line); }

  /* ---- the 30-second version ---- */
  ol.quick { list-style:none; margin:0; padding:0; display:flex;
             flex-direction:column; gap:.95rem; }
  ol.quick li { display:grid; grid-template-columns:.4rem 1fr; gap:.9rem;
                align-items:start; }
  ol.quick li::before { content:""; width:.4rem; height:.4rem; border-radius:50%;
                        background:var(--ink); margin-top:.62em; }

  /* ---- macro ---- */
  dl.macro { margin:0; display:flex; flex-direction:column; gap:1.5rem; }
  dl.macro dt { font-family:var(--ui); font-size:.94rem; font-weight:580;
                line-height:1.5; letter-spacing:-.008em; }
  dl.macro dd { margin:.45rem 0 0; color:var(--ink-2); font-size:1rem; }
  .lead { font-family:var(--ui); font-size:.63rem; font-weight:680;
          letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3);
          margin-right:.55rem; }

  /* ---- entries ---- */
  .entries { display:flex; flex-direction:column; gap:1.1rem; }
  article.entry { background:var(--paper); border:1px solid var(--line);
                  border-radius:14px; padding:1.5rem 1.6rem;
                  display:flex; flex-direction:column; gap:1rem;
                  transition:border-color .28s var(--ease),
                             box-shadow .28s var(--ease); }
  article.entry:hover { border-color:#D8D7D1;
                        box-shadow:0 12px 32px -20px rgba(12,13,14,.30); }
  .entry-head { display:flex; flex-wrap:wrap; align-items:center;
                gap:.5rem .8rem; }
  .tick { font-family:var(--ui); font-size:1.35rem; font-weight:660;
          letter-spacing:-.02em; display:inline-flex; align-items:center;
          gap:.42rem; }
  .tick.up{color:var(--up);} .tick.down{color:var(--down);} .tick.flat{color:var(--ink);}
  .arrow { font-size:.6em; }
  .move { font-family:var(--mono); font-size:.76rem; font-variant-numeric:tabular-nums;
          color:var(--ink-3); margin-left:auto; }
  .move.up{color:var(--up);} .move.down{color:var(--down);}

  .happened { font-size:1.08rem; margin:0; letter-spacing:-.004em; }
  .grade { font-family:var(--ui); font-size:.62rem; font-weight:680;
           letter-spacing:.1em; text-transform:uppercase; color:var(--ink-3);
           margin:-.5rem 0 0; }

  .figures { font-family:var(--mono); font-size:.775rem; line-height:1.85;
             font-variant-numeric:tabular-nums; color:var(--ink-2);
             background:var(--wash); border:1px solid var(--line-2);
             border-radius:10px; padding:.9rem 1rem; margin:0; overflow-x:auto; }
  .figures b { color:var(--ink); font-weight:600; }
  .why { margin:0; color:var(--ink-2); }

  .footline { display:flex; flex-direction:column; gap:.55rem; font-size:.93rem;
              color:var(--ink-2); padding-top:.55rem;
              border-top:1px solid var(--line-2); }
  .footline span.k { font-family:var(--ui); font-size:.61rem; font-weight:680;
                     letter-spacing:.1em; text-transform:uppercase;
                     color:var(--ink-2); margin-right:.5rem; }
  .flag { background:var(--amber-wash); border:1px solid #F0EAD6;
          border-left:2px solid var(--amber); color:var(--ink-2);
          padding:.7rem .85rem; border-radius:8px; font-size:.93rem; }
  .flag span.k { color:var(--amber); }

  .note { background:var(--paper); border:1px solid var(--line);
          border-left:2px solid var(--ink); border-radius:10px;
          padding:1.15rem 1.25rem; display:flex; flex-direction:column;
          gap:.55rem; margin-top:.7rem; }
  .note h3 { font-family:var(--ui); font-size:.64rem; font-weight:680;
             letter-spacing:.1em; text-transform:uppercase; color:var(--ink);
             margin:0; }
  .note p { margin:0; color:var(--ink-2); font-size:1rem; }

  .quiet { font-size:1rem; color:var(--ink-2); margin:0; }
  .quiet b { color:var(--ink); font-weight:600; }

  ul.dates { list-style:none; margin:0; padding:0; display:flex;
             flex-direction:column; gap:.6rem; }
  ul.dates li { font-size:1rem; color:var(--ink-2); display:flex; gap:.85rem;
                align-items:baseline; }
  ul.dates .d { font-family:var(--mono); font-size:.72rem; color:var(--ink);
                font-variant-numeric:tabular-nums; min-width:4.6rem;
                border:1px solid var(--line); border-radius:6px;
                padding:.2rem .5rem; text-align:center; }

  /* ---- ticker index ---- */
  .tindex { display:flex; flex-direction:column; gap:.6rem; }
  .trow { display:grid; grid-template-columns:4.4rem 1fr; gap:.7rem;
          align-items:center; }
  .tname { font-family:var(--ui); font-size:.82rem; font-weight:660;
           letter-spacing:-.01em; }
  .tname.up{color:var(--up);} .tname.down{color:var(--down);}
  .tname.flat{color:var(--ink);}
  .chips { display:flex; flex-wrap:wrap; gap:.35rem; }
  .chip { font-family:var(--mono); font-size:.68rem; font-variant-numeric:tabular-nums;
          border:1px solid var(--line); border-radius:6px; padding:.16rem .45rem;
          color:var(--ink-3); white-space:nowrap; background:var(--paper);
          transition:border-color .2s var(--ease), color .2s var(--ease); }
  .chip:hover { border-color:currentColor; }
  .chip i { font-style:normal; margin-left:.35rem; }
  .chip.up { color:var(--up); } .chip.down { color:var(--down); }

  /* ---- archive ---- */
  details.day { border:1px solid var(--line); border-radius:11px;
                background:var(--paper); padding:.95rem 1.1rem; margin-bottom:.6rem;
                transition:border-color .25s var(--ease); }
  details.day:hover { border-color:#D8D7D1; }
  details.day summary { cursor:pointer; font-family:var(--mono); font-size:.78rem;
                        color:var(--ink-2); font-variant-numeric:tabular-nums;
                        list-style:none; display:flex; gap:.8rem; align-items:center; }
  details.day summary::-webkit-details-marker { display:none; }
  details.day summary::before { content:"+"; color:var(--ink-3); font-size:1rem;
                                width:.9rem; text-align:center;
                                transition:transform .3s var(--ease); }
  details.day[open] summary::before { content:"\\2013"; transform:rotate(180deg); }
  details.day summary:focus-visible { outline:2px solid var(--ink); outline-offset:3px; }
  details.day summary .sum { color:var(--ink-3); }
  details.day .archive-body { padding-top:1.7rem; display:flex;
                              flex-direction:column; gap:2.4rem;
                              animation:unfold .4s var(--ease) both; }
  details.day .archive-body .band > h2 { font-size:.64rem; }
  @keyframes unfold { from { opacity:0; transform:translateY(-6px); } }

  .empty { font-size:.97rem; color:var(--ink-3); font-style:italic; }

  /* ---- about ---- */
  .about .card { background:var(--wash); border:1px solid var(--line);
                 border-radius:16px; padding:2rem 1.9rem;
                 display:flex; flex-direction:column; gap:1.3rem; }
  .who { display:flex; align-items:center; gap:1rem; }
  .mono-badge { width:3rem; height:3rem; flex:0 0 auto; border-radius:50%;
                display:grid; place-items:center; font-family:var(--ui);
                font-size:.85rem; font-weight:660; letter-spacing:.02em;
                color:var(--paper); background:var(--ink); }
  .who-t { display:flex; flex-direction:column; gap:.2rem; }
  .who-t b { font-family:var(--ui); font-size:1.15rem; font-weight:620;
             letter-spacing:-.018em; }
  .who-t i { font-style:normal; font-family:var(--ui); font-size:.72rem;
             font-weight:580; color:var(--ink-3); }
  .bio { display:flex; flex-direction:column; gap:.85rem; }
  .bio p { margin:0; color:var(--ink-2); font-size:1.02rem; }
  .bio b { color:var(--ink); font-weight:600; }
  .pills { display:flex; flex-wrap:wrap; gap:.55rem; padding-top:.15rem; }
  .pill { font-family:var(--ui); font-size:.74rem; font-weight:560;
          text-decoration:none; color:var(--ink-2); background:var(--paper);
          border:1px solid var(--line); border-radius:7px; padding:.44rem .9rem;
          transition:color .22s var(--ease), border-color .22s var(--ease),
                     transform .22s var(--ease); }
  .pill:hover { color:var(--ink); border-color:var(--ink); transform:translateY(-1px); }

  /* ---- colophon ---- */
  .colophon { border-top:1px solid var(--line); padding-top:1.8rem; display:flex;
              flex-direction:column; gap:1rem; font-size:.88rem; color:var(--ink-3); }
  .colophon dl { margin:0; display:grid; grid-template-columns:auto 1fr;
                 gap:.5rem 1.1rem; }
  .colophon dt { font-family:var(--ui); font-size:.61rem; font-weight:680;
                 letter-spacing:.1em; text-transform:uppercase; color:var(--ink-2);
                 padding-top:.2rem; }
  .colophon dd { margin:0; }
  .colophon .disclaim { font-style:italic; }
  a { color:var(--ink); }

  /* ---- motion, applied only once the head script proves JS runs ---- */
  .js .reveal { opacity:0; transform:translateY(14px);
                transition:opacity .55s var(--ease), transform .55s var(--ease); }
  .js .reveal.in { opacity:1; transform:none; }
  .js .masthead .brandrow, .js .masthead h1, .js .masthead .dateline {
    animation:rise .65s var(--ease) both; }
  .js .masthead h1 { animation-delay:.06s; }
  .js .masthead .dateline { animation-delay:.13s; }
  @keyframes rise { from { opacity:0; transform:translateY(12px); } }

  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior:auto; }
    *, *::before, *::after { animation:none !important;
                             transition-duration:.01ms !important; }
    .js .reveal { opacity:1; transform:none; }
  }

  @media (max-width:36rem) {
    body { font-size:17px; }
    .wrap { padding:3.6rem 1.15rem 4.5rem; gap:2.6rem; }
    .masthead { gap:1.2rem; padding-bottom:1.7rem; }
    .move { margin-left:0; width:100%; }
    article.entry { padding:1.15rem 1.1rem; border-radius:12px; }
    .about .card { padding:1.4rem 1.2rem; border-radius:13px; }
    .topbar { padding:.6rem 1.15rem; }
    .tb-date { display:none; }
    .trow { grid-template-columns:1fr; gap:.3rem; }
  }
"""

JS = """
(function () {
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var bar = document.querySelector('.progress');
  var top = document.querySelector('.topbar');
  var mast = document.querySelector('.masthead');

  // Scroll progress + sticky bar, both driven by one rAF-throttled handler.
  var ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      var h = document.documentElement.scrollHeight - window.innerHeight;
      var p = h > 0 ? window.scrollY / h : 0;
      if (bar) bar.style.transform = 'scaleX(' + p + ')';
      if (top && mast) {
        var past = window.scrollY > mast.offsetHeight + 40;
        top.classList.toggle('show', past);
      }
      ticking = false;
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // Reveal on scroll. Sections inside a closed <details> are never observed,
  // so they are shown outright when the block is opened.
  var targets = document.querySelectorAll('.reveal');
  if (reduce || !('IntersectionObserver' in window)) {
    targets.forEach(function (el) { el.classList.add('in'); });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (!en.isIntersecting) return;
      en.target.classList.add('in');
      io.unobserve(en.target);
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });

  targets.forEach(function (el, i) {
    if (el.closest('details')) { el.classList.add('in'); return; }
    el.style.transitionDelay = Math.min(i, 6) * 45 + 'ms';
    io.observe(el);
  });

  setTimeout(function () {
    document.querySelectorAll('.reveal:not(.in)').forEach(function (el) {
      var r = el.getBoundingClientRect();
      if (r.top < window.innerHeight) el.classList.add('in');
    });
  }, 1200);

  document.querySelectorAll('details.day').forEach(function (d) {
    d.addEventListener('toggle', function () {
      if (!d.open) return;
      d.querySelectorAll('.reveal').forEach(function (el) { el.classList.add('in'); });
    });
  });
})();
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>v2v.investing | Ticker Brief</title>
<meta name="description" content="A daily pre-market brief on twelve tickers, written to explain why each number changes what a company is worth.">
<meta name="color-scheme" content="light">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<script>{head_js}</script>
<style>{css}</style>
</head>
<body>
<div class="progress" aria-hidden="true"></div>
<div class="topbar" aria-hidden="true">
  <span class="tb-mark">v2v.investing</span>
  <span class="tb-date">Ticker Brief</span>
</div>
<div class="wrap">
  <header class="masthead">
    <div class="brandrow">
      <div class="wordmark">v2v.investing</div>
      <a class="social" href="https://www.tiktok.com/@v2v.investing"
         target="_blank" rel="noopener noreferrer">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16.6 5.82A4.28 4.28 0 0 1 15.54 3h-3.09v12.4a2.59 2.59 0 0 1-2.59 2.5 2.59 2.59 0 1 1 .77-5.06V9.7a5.68 5.68 0 0 0-.77-.05A5.67 5.67 0 1 0 15.54 15.4V9.01a7.35 7.35 0 0 0 4.3 1.38V7.3a4.29 4.29 0 0 1-3.24-1.48Z"/></svg>
        TikTok
      </a>
    </div>
    <h1>{headline}</h1>
    {dateline}
  </header>
  {body}
  {tindex}
  {archive}
  {about}
  <footer class="colophon">
    <dl>
      <dt>Direction</dt>
      <dd>&#9650; bullish &middot; &#9660; bearish &middot; &#9679; neutral. Describes what the data changes, not what the price will do.</dd>
      <dt>Strength</dt>
      <dd>Major = 3%+ &middot; Notable = 1&ndash;3% &middot; Minor = under 1%.</dd>
      <dt>Flagged</dt>
      <dd>Highlighted blocks mark items where the stock has <em>not</em> moved in line with the data. These are the cases worth a second look.</dd>
      <dt>Archive</dt>
      <dd>{count} edition(s) on file. Every brief is kept permanently in the repository behind this page.</dd>
      <dt>Sources</dt>
      <dd>Company filings and results, and reported figures from the financial press. Opinion pieces and analyst price targets are excluded by design.</dd>
    </dl>
    <p class="disclaim">This is a record of what was reported and what it changes mechanically. It is not a prediction, and it is not investment advice.</p>
  </footer>
</div>
<script>{js}</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
