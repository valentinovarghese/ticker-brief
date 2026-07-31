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

import json
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
        out.append(ed)
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
    return ('<section class="band"><h2>The 30-second version</h2>'
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
    return ('<section class="band"><h2>Market-wide</h2>'
            f'<dl class="macro">{body}</dl></section>')


def render_note(note):
    return (f'<div class="note"><h3>{note["title"]}</h3>'
            f'<p>{note["body"]}</p></div>')


def render_entry(e):
    head = [
        f'<span class="tick {e["dir"]}">'
        f'<span class="arrow">{ {"up": "&#9650;", "down": "&#9660;"}.get(e["dir"], "&#9679;") }</span> '
        f'{e["ticker"]}</span>',
        f'<span class="strength {e["strength"]}">{e["strength_label"]}</span>',
    ]
    if e.get("move"):
        tone = e.get("move_tone", "flat")
        head.append(f'<span class="move {tone}">{e["move"]}</span>')

    parts = [f'<div class="entry-head">{"".join(head)}</div>',
             f'<p class="happened">{e["happened"]}</p>']

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
    return ('<section class="band"><h2>Items &middot; sorted by size</h2>'
            f'<div class="entries">{body}</div></section>')


def render_readthrough(ed):
    rt = ed.get("readthrough")
    return ('<section class="band"><h2>Read-through</h2>'
            f'{render_note(rt)}</section>') if rt else ""


def render_nothing(ed):
    nm = ed.get("nothing_material")
    if not nm or not nm.get("tickers"):
        return ""
    tickers = " &middot; ".join(nm["tickers"])
    out = (f'<section class="band"><h2>Nothing material</h2>'
           f'<p class="quiet"><b>{tickers}</b> &mdash; no company-specific '
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
    return ('<section class="band"><h2>Earnings within 14 days</h2>'
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

    return ('<section class="band"><h2>By ticker &middot; every day on file</h2>'
            f'<div class="tindex">{"".join(rows)}</div></section>')


def render_archive(older):
    if not older:
        return ('<section class="band"><h2>Previous days</h2>'
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
    return (f'<section class="band"><h2>Previous days &middot; {len(older)} '
            f'archived</h2>{"".join(blocks)}</section>')


# ---------------------------------------------------------------- page

def render_page(editions):
    latest, older = editions[0], editions[1:]
    return PAGE.format(
        css=CSS,
        dateline=render_gauge(latest),
        headline=latest["headline"],
        body=render_body(latest),
        tindex=render_ticker_index(editions),
        archive=render_archive(older),
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
  :root {
    --ground:#F6F6F4; --surface:#FFFFFF; --ink:#14181C; --ink-soft:#414C55;
    --ink-mute:#6B767F; --rule:#DCDFDB; --rule-soft:#E8EAE6; --slate:#2F4858;
    --bull:#146B4A; --bear:#A33227; --flag-bg:#F0EDE3; --flag-ink:#6E5A18;
    --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
    --col:44rem;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ground:#12161A; --surface:#181D22; --ink:#E7EAE7; --ink-soft:#B4BEC4;
      --ink-mute:#8B979F; --rule:#2B323A; --rule-soft:#222932; --slate:#9BBACD;
      --bull:#4FBF8B; --bear:#E0796C; --flag-bg:#232019; --flag-ink:#CBB66E;
    }
  }
  :root[data-theme="dark"] {
    --ground:#12161A; --surface:#181D22; --ink:#E7EAE7; --ink-soft:#B4BEC4;
    --ink-mute:#8B979F; --rule:#2B323A; --rule-soft:#222932; --slate:#9BBACD;
    --bull:#4FBF8B; --bear:#E0796C; --flag-bg:#232019; --flag-ink:#CBB66E;
  }
  :root[data-theme="light"] {
    --ground:#F6F6F4; --surface:#FFFFFF; --ink:#14181C; --ink-soft:#414C55;
    --ink-mute:#6B767F; --rule:#DCDFDB; --rule-soft:#E8EAE6; --slate:#2F4858;
    --bull:#146B4A; --bear:#A33227; --flag-bg:#F0EDE3; --flag-ink:#6E5A18;
  }

  body { background:var(--ground); color:var(--ink); font-family:var(--serif);
         font-size:17px; line-height:1.6; -webkit-font-smoothing:antialiased; }
  .wrap { max-width:var(--col); margin:0 auto; padding:3rem 1.4rem 5rem;
          display:flex; flex-direction:column; gap:2.75rem; }

  .masthead { display:flex; flex-direction:column; gap:1rem; }
  .wordmark { font-family:var(--sans); font-size:.72rem; font-weight:600;
              letter-spacing:.22em; text-transform:uppercase; color:var(--slate); }
  .masthead h1 { font-size:clamp(1.6rem,4.4vw,2.15rem); line-height:1.24;
                 font-weight:600; text-wrap:balance; margin:0; }
  .dateline { font-family:var(--mono); font-size:.76rem; color:var(--ink-mute);
              display:flex; flex-wrap:wrap; gap:.5rem 1.1rem;
              font-variant-numeric:tabular-nums; }
  .dateline .gauge { color:var(--bull); }

  .band { display:flex; flex-direction:column; gap:.9rem; }
  .band > h2 { font-family:var(--sans); font-size:.7rem; font-weight:650;
               letter-spacing:.18em; text-transform:uppercase; color:var(--ink-mute);
               margin:0; padding-bottom:.55rem; border-bottom:1px solid var(--rule); }

  ol.quick { list-style:none; margin:0; padding:0; display:flex;
             flex-direction:column; gap:.7rem; counter-reset:q; }
  ol.quick li { counter-increment:q; display:grid; grid-template-columns:1.6rem 1fr;
                gap:.35rem; align-items:baseline; }
  ol.quick li::before { content:counter(q); font-family:var(--mono); font-size:.72rem;
                        color:var(--ink-mute); font-variant-numeric:tabular-nums; }

  dl.macro { margin:0; display:flex; flex-direction:column; gap:1.1rem; }
  dl.macro dt { font-family:var(--sans); font-size:.88rem; font-weight:600; }
  dl.macro dd { margin:.2rem 0 0; color:var(--ink-soft); font-size:.97rem; }
  .lead { font-family:var(--sans); font-size:.66rem; font-weight:650;
          letter-spacing:.14em; text-transform:uppercase; color:var(--slate);
          margin-right:.45rem; }

  .entries { display:flex; flex-direction:column; }
  article.entry { padding:1.6rem 0; border-bottom:1px solid var(--rule-soft);
                  display:flex; flex-direction:column; gap:.85rem; }
  article.entry:first-of-type { padding-top:.5rem; }
  .entry-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:.5rem .75rem; }
  .tick { font-family:var(--sans); font-size:1.28rem; font-weight:680; letter-spacing:.03em; }
  .tick.up{color:var(--bull);} .tick.down{color:var(--bear);} .tick.flat{color:var(--ink);}
  .arrow { font-size:.85em; }
  .strength { font-family:var(--sans); font-size:.63rem; font-weight:650;
              letter-spacing:.15em; text-transform:uppercase; padding:.2rem .5rem;
              border:1px solid var(--rule); color:var(--ink-mute); border-radius:2px; }
  .strength.major { color:var(--ink); border-color:currentColor; }
  .move { font-family:var(--mono); font-size:.82rem; font-variant-numeric:tabular-nums;
          color:var(--ink-mute); margin-left:auto; }
  .move.up{color:var(--bull);} .move.down{color:var(--bear);}

  .happened { font-size:1.02rem; margin:0; }
  .figures { font-family:var(--mono); font-size:.8rem; line-height:1.75;
             font-variant-numeric:tabular-nums; color:var(--ink-soft);
             background:var(--surface); border:1px solid var(--rule-soft);
             border-radius:2px; padding:.7rem .85rem; margin:0; overflow-x:auto; }
  .figures b { color:var(--ink); font-weight:600; }
  .why { margin:0; color:var(--ink-soft); }

  .footline { display:flex; flex-direction:column; gap:.4rem; font-size:.9rem;
              color:var(--ink-mute); }
  .footline span.k { font-family:var(--sans); font-size:.64rem; font-weight:650;
                     letter-spacing:.13em; text-transform:uppercase; margin-right:.4rem; }
  .flag { background:var(--flag-bg); color:var(--flag-ink); padding:.55rem .75rem;
          border-radius:2px; font-size:.9rem; }
  .flag span.k { color:var(--flag-ink); }

  .note { background:var(--surface); border:1px solid var(--rule-soft);
          border-radius:2px; padding:1rem 1.1rem; display:flex;
          flex-direction:column; gap:.45rem; margin-top:.4rem; }
  .note h3 { font-family:var(--sans); font-size:.68rem; font-weight:650;
             letter-spacing:.15em; text-transform:uppercase; color:var(--slate); margin:0; }
  .note p { margin:0; color:var(--ink-soft); font-size:.97rem; }

  .quiet { font-size:.95rem; color:var(--ink-mute); margin:0; }
  .quiet b { color:var(--ink); font-weight:600; }

  ul.dates { list-style:none; margin:0; padding:0; display:flex;
             flex-direction:column; gap:.5rem; }
  ul.dates li { font-size:.95rem; color:var(--ink-soft); display:flex; gap:.7rem; }
  ul.dates .d { font-family:var(--mono); font-size:.8rem; color:var(--ink);
                font-variant-numeric:tabular-nums; min-width:5.2rem; }

  .tindex { display:flex; flex-direction:column; gap:.5rem; }
  .trow { display:grid; grid-template-columns:4.2rem 1fr; gap:.6rem;
          align-items:baseline; }
  .tname { font-family:var(--sans); font-size:.82rem; font-weight:680;
           letter-spacing:.03em; }
  .tname.up{color:var(--bull);} .tname.down{color:var(--bear);}
  .tname.flat{color:var(--ink);}
  .chips { display:flex; flex-wrap:wrap; gap:.3rem; }
  .chip { font-family:var(--mono); font-size:.7rem; font-variant-numeric:tabular-nums;
          border:1px solid var(--rule); border-radius:2px; padding:.12rem .38rem;
          color:var(--ink-mute); white-space:nowrap; }
  .chip i { font-style:normal; margin-left:.35rem; }
  .chip.up { color:var(--bull); border-color:currentColor; }
  .chip.down { color:var(--bear); border-color:currentColor; }

  details.day { border-top:1px solid var(--rule); padding:.9rem 0; }
  details.day summary { cursor:pointer; font-family:var(--mono); font-size:.82rem;
                        color:var(--ink-soft); font-variant-numeric:tabular-nums;
                        list-style:none; display:flex; gap:.7rem; align-items:baseline; }
  details.day summary::-webkit-details-marker { display:none; }
  details.day summary::before { content:"+"; color:var(--ink-mute); font-size:.9rem; }
  details.day[open] summary::before { content:"\\2013"; }
  details.day summary:focus-visible { outline:2px solid var(--slate); outline-offset:3px; }
  details.day summary .sum { color:var(--ink-mute); }
  details.day .archive-body { padding-top:1.4rem; display:flex;
                              flex-direction:column; gap:2rem; }
  details.day .archive-body .band > h2 { font-size:.64rem; }

  .empty { font-size:.93rem; color:var(--ink-mute); font-style:italic; }

  .colophon { border-top:1px solid var(--rule); padding-top:1.3rem; display:flex;
              flex-direction:column; gap:.7rem; font-size:.85rem; color:var(--ink-mute); }
  .colophon dl { margin:0; display:grid; grid-template-columns:auto 1fr; gap:.35rem .9rem; }
  .colophon dt { font-family:var(--sans); font-size:.64rem; font-weight:650;
                 letter-spacing:.13em; text-transform:uppercase; padding-top:.15rem; }
  .colophon dd { margin:0; }
  .colophon .disclaim { font-style:italic; }
  a { color:var(--slate); }

  @media (max-width:34rem) {
    body { font-size:16px; }
    .wrap { padding:2.2rem 1.1rem 3.5rem; gap:2.2rem; }
    .move { margin-left:0; width:100%; }
  }
"""

PAGE = """<title>v2v.investing — Ticker Brief</title>
<style>{css}</style>
<div class="wrap">
  <header class="masthead">
    <div class="wordmark">v2v.investing</div>
    <h1>{headline}</h1>
    {dateline}
  </header>
  {body}
  {tindex}
  {archive}
  <footer class="colophon">
    <dl>
      <dt>Direction</dt>
      <dd>&#9650; bullish &middot; &#9660; bearish &middot; &#9679; neutral &mdash; describes what the data changes, not what the price will do.</dd>
      <dt>Strength</dt>
      <dd>Major = 3%+ &middot; Notable = 1&ndash;3% &middot; Minor = under 1%.</dd>
      <dt>Flagged</dt>
      <dd>Highlighted blocks mark items where the stock has <em>not</em> moved in line with the data &mdash; the cases worth a second look.</dd>
      <dt>Archive</dt>
      <dd>{count} edition(s) on file. Every brief is kept permanently in the repository behind this page.</dd>
      <dt>Sources</dt>
      <dd>Company filings and results, and reported figures from the financial press. Opinion pieces and analyst price targets are excluded by design.</dd>
    </dl>
    <p class="disclaim">This is a record of what was reported and what it changes mechanically. It is not a prediction, and it is not investment advice.</p>
  </footer>
</div>
"""


if __name__ == "__main__":
    main()
