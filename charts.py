#!/usr/bin/env python3
"""
Draw a 3-month daily candlestick SVG per ticker into charts/.

Run separately from build.py (python3 charts.py) so a data-source outage
never blocks the daily brief from publishing. build.py links a ticker to
its local SVG when one exists and falls back to an external chart service
when it does not, so this script failing degrades the page rather than
breaking it.

Every SVG is self-contained: no external references, no script, no fonts
beyond the generic families. That keeps it servable under the page's own
img-src 'self' policy and viewable as a plain file.

Usage:  python3 charts.py           # fetch and draw all tickers
        python3 charts.py --demo    # draw from synthetic data, to test
                                    # rendering without a network source
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "charts"

TICKERS = ("AAPL", "AMZN", "TSLA", "PLTR", "MSFT", "GOOGL",
           "HOOD", "NVDA", "INTC", "NBIS", "MRVL", "META")

# Same ink and semantics as the page: colour means direction, nothing else.
INK, MUTE, LINE, PAPER = "#0C0D0E", "#6E747B", "#E7E6E1", "#FFFFFF"
UP, DOWN = "#046A44", "#B33124"

W, H = 720, 320
PAD_L, PAD_R, PAD_T, PAD_B = 8, 58, 44, 26
SESSIONS = 63          # about three months of trading days


# ------------------------------------------------------------------ data

def fetch_ohlc(ticker):
    """Daily OHLC, newest last, as [(date, o, h, l, c)]. None if unavailable.

    Sources are tried in order and every failure is silent by design: the
    caller treats None as "no chart today" and the page falls back.
    """
    for source in (_from_alphavantage, _from_stooq):
        try:
            rows = drop_incomplete(source(ticker))
            if rows and len(rows) >= 20:
                return rows[-SESSIONS:]
        except Exception:
            continue
    return None


def drop_incomplete(rows):
    """Discard a final bar for a session that has not finished.

    The routine runs before the opening bell, and the data source will
    happily return a bar dated today built from premarket prints. Drawing
    it as a candle would put a partial, thinly traded bar on the chart
    looking exactly like a settled day. Only bars for sessions that have
    actually closed belong here.
    """
    if not rows:
        return rows
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return rows
    closed = now.replace(hour=16, minute=5, second=0, microsecond=0)
    today = now.strftime("%Y-%m-%d")
    if rows[-1][0] == today and now < closed:
        return rows[:-1]
    return rows


def _curl(url):
    r = subprocess.run(["curl", "-sS", "--max-time", "25",
                        "-H", "User-Agent: Mozilla/5.0", url],
                       capture_output=True, text=True, timeout=40)
    return r.stdout


def parse_alphavantage(payload):
    """Rows oldest-first from an Alpha Vantage TIME_SERIES_DAILY body.

    Alpha Vantage answers HTTP 200 for throttling and bad keys alike,
    putting the reason in a "Note", "Information" or "Error Message" key,
    so the absence of the series is the only reliable failure signal.
    """
    data = json.loads(payload)
    series = data.get("Time Series (Daily)")
    if not isinstance(series, dict):
        reason = (data.get("Note") or data.get("Information")
                  or data.get("Error Message") or "unrecognised response")
        raise ValueError(str(reason)[:120])
    rows = []
    for day in sorted(series):
        bar = series[day]
        rows.append((day, float(bar["1. open"]), float(bar["2. high"]),
                     float(bar["3. low"]), float(bar["4. close"]),
                     float(bar.get("5. volume", 0))))
    return rows


def _from_alphavantage(ticker):
    # Tolerate a key pasted with surrounding whitespace or a trailing full
    # stop, which is easy to leave behind when copying it into a .env box.
    key = os.environ.get("ALPHAVANTAGE_KEY", "").strip().strip(".")
    if not key:
        return None
    return parse_alphavantage(_curl(
        "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY"
        f"&symbol={ticker}&outputsize=compact&apikey={key}"))


def _from_stooq(ticker):
    text = _curl(f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d")
    if not text.startswith("Date,"):
        return None                      # a challenge page, not a CSV
    rows = []
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            rows.append((parts[0], float(parts[1]), float(parts[2]),
                         float(parts[3]), float(parts[4]),
                         float(parts[5]) if len(parts) > 5 else 0.0))
        except ValueError:
            continue
    return rows


def demo_rows(seed):
    """Deterministic pseudo-random walk, for testing the renderer alone."""
    rows, price, state = [], 100.0, seed * 7919 + 13
    for i in range(SESSIONS):
        state = (state * 1103515245 + 12345) % (2 ** 31)
        drift = ((state >> 16) % 1000 - 480) / 100.0
        o = price
        c = max(1.0, o + drift)
        state = (state * 1103515245 + 12345) % (2 ** 31)
        wick = ((state >> 16) % 200) / 100.0
        h, lo = max(o, c) + wick, max(0.5, min(o, c) - wick)
        rows.append((f"day{i}", o, h, lo, c, 1e6 + (state % 900000)))
        price = c
    return rows


# ---------------------------------------------------------------- render

def render(ticker, rows):
    lows = [r[3] for r in rows]
    highs = [r[2] for r in rows]
    lo, hi = min(lows), max(highs)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.06, hi + span * 0.06
    span = hi - lo

    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    step = plot_w / len(rows)
    body = max(1.6, step * 0.62)

    def y(v):
        return PAD_T + plot_h - (v - lo) / span * plot_h

    parts = []
    # Four horizontal guides, labelled on the right so the candles stay flush.
    for i in range(4):
        v = lo + span * (i / 3)
        gy = round(y(v), 1)
        parts.append(f'<line x1="{PAD_L}" y1="{gy}" x2="{PAD_L + plot_w}" '
                     f'y2="{gy}" stroke="{LINE}" stroke-width="1"/>')
        parts.append(f'<text x="{PAD_L + plot_w + 8}" y="{gy + 3.5}" '
                     f'fill="{MUTE}" font-size="10">{v:,.2f}</text>')

    for i, bar in enumerate(rows):
        o, h, l, c = bar[1], bar[2], bar[3], bar[4]
        cx = PAD_L + step * (i + 0.5)
        colour = UP if c >= o else DOWN
        top, bot = y(max(o, c)), y(min(o, c))
        parts.append(f'<line x1="{cx:.1f}" y1="{y(h):.1f}" x2="{cx:.1f}" '
                     f'y2="{y(l):.1f}" stroke="{colour}" stroke-width="1"/>')
        parts.append(f'<rect x="{cx - body / 2:.1f}" y="{top:.1f}" '
                     f'width="{body:.1f}" height="{max(1.0, bot - top):.1f}" '
                     f'fill="{colour}"/>')

    first_close, last_close = rows[0][4], rows[-1][4]
    pct = (last_close / first_close - 1) * 100 if first_close else 0
    tone = UP if pct >= 0 else DOWN
    span_label = f"{rows[0][0]} to {rows[-1][0]}" if "-" in rows[0][0] else \
                 f"{len(rows)} sessions"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" \
width="{W}" height="{H}" role="img" \
aria-label="{ticker} daily candles, last {len(rows)} sessions">
<rect width="{W}" height="{H}" fill="{PAPER}"/>
<text x="{PAD_L}" y="22" fill="{INK}" font-size="16" font-weight="600" \
font-family="system-ui,-apple-system,Segoe UI,Roboto,sans-serif">{ticker}</text>
<text x="{PAD_L + 52}" y="22" fill="{MUTE}" font-size="11" \
font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace">\
daily candles &#183; {span_label}</text>
<text x="{W - PAD_R + 8}" y="22" fill="{tone}" font-size="12" text-anchor="end" \
font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" \
transform="translate({PAD_R - 8},0)">{pct:+.1f}%</text>
<g font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace">
{chr(10).join(parts)}
</g>
<text x="{PAD_L}" y="{H - 8}" fill="{MUTE}" font-size="9.5" \
font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace">\
v2v.investing &#183; last close {last_close:,.2f}</text>
</svg>
'''


def sha256_src(source):
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def cache_dir():
    return OUT / "data"


def cached(ticker):
    """Last successful fetch, so a throttled day redraws instead of failing."""
    f = cache_dir() / f"{ticker}.json"
    if not f.exists():
        return None
    try:
        return [tuple(r) for r in json.loads(f.read_text(encoding="utf-8"))]
    except (json.JSONDecodeError, TypeError):
        return None


# ------------------------------------------------------- interactive page

CHART_JS = r"""
(function () {
  var D = window.__BARS__, TICKER = window.__TICKER__;
  var cv = document.getElementById('c'), ctx = cv.getContext('2d');
  var read = document.getElementById('read');
  var INK='#0C0D0E', MUTE='#6E747B', LINE='#EFEEEA', GRID='#F6F5F2',
      UP='#046A44', DOWN='#B33124', PAPER='#FFFFFF';
  var PADR = 66, PADT = 8, PADB = 30, VOLH = 0.18, GAPV = 14;
  var view = { from: 0, to: D.length };      // visible slice, for zooming
  var hover = null, dpr = 1, W = 0, H = 0;

  function fmt(v, d) { return v.toLocaleString('en-US',
      { minimumFractionDigits: d === undefined ? 2 : d,
        maximumFractionDigits: d === undefined ? 2 : d }); }
  function fmtVol(v) {
    if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
    return String(v);
  }

  function resize() {
    dpr = window.devicePixelRatio || 1;
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function slice() { return D.slice(view.from, view.to); }

  function geom() {
    var bars = slice();
    var priceH = (H - PADT - PADB) * (1 - VOLH) - GAPV;
    var volTop = PADT + priceH + GAPV;
    var volH = (H - PADT - PADB) - priceH - GAPV;
    var lo = Infinity, hi = -Infinity, vmax = 0;
    bars.forEach(function (b) {
      if (b[3] < lo) lo = b[3];
      if (b[2] > hi) hi = b[2];
      if (b[5] > vmax) vmax = b[5];
    });
    var pad = (hi - lo) * 0.06 || 1;
    lo -= pad; hi += pad;
    var plotW = W - PADR;
    return { bars: bars, lo: lo, hi: hi, vmax: vmax || 1, plotW: plotW,
             priceH: priceH, volTop: volTop, volH: volH,
             step: plotW / bars.length };
  }

  function yOf(g, v) { return PADT + g.priceH - (v - g.lo) / (g.hi - g.lo) * g.priceH; }

  // A "nice" step keeps gridline prices on round numbers as you zoom.
  function niceStep(range, target) {
    var raw = range / target, mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var n = raw / mag;
    var step = n >= 7.5 ? 10 : n >= 3.5 ? 5 : n >= 1.5 ? 2 : 1;
    return step * mag;
  }

  function draw() {
    var g = geom();
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = PAPER; ctx.fillRect(0, 0, W, H);
    ctx.font = '11px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace';
    ctx.textBaseline = 'middle';

    // Price gridlines. Density follows height, so a tall window gets more
    // levels rather than the same four stretched apart.
    var target = Math.max(4, Math.min(14, Math.round(g.priceH / 46)));
    var step = niceStep(g.hi - g.lo, target);
    var start = Math.ceil(g.lo / step) * step;
    ctx.textAlign = 'left';
    for (var p = start; p <= g.hi; p += step) {
      var y = Math.round(yOf(g, p)) + 0.5;
      ctx.strokeStyle = GRID; ctx.beginPath();
      ctx.moveTo(0, y); ctx.lineTo(g.plotW, y); ctx.stroke();
      ctx.fillStyle = MUTE; ctx.fillText(fmt(p), g.plotW + 8, y);
    }

    // Date ticks, thinned to whatever fits.
    var every = Math.max(1, Math.ceil(g.bars.length / Math.max(2, Math.floor(W / 92))));
    ctx.textAlign = 'center';
    for (var i = 0; i < g.bars.length; i += every) {
      var x = g.step * (i + 0.5);
      ctx.strokeStyle = GRID; ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, PADT); ctx.lineTo(Math.round(x) + 0.5, PADT + g.priceH);
      ctx.stroke();
      ctx.fillStyle = MUTE;
      ctx.fillText(g.bars[i][0].slice(5), x, H - PADB / 2);
    }

    var body = Math.max(1, g.step * 0.66);
    for (var j = 0; j < g.bars.length; j++) {
      var b = g.bars[j], cx = g.step * (j + 0.5);
      var col = b[4] >= b[1] ? UP : DOWN;
      ctx.strokeStyle = col; ctx.fillStyle = col;
      ctx.beginPath();
      ctx.moveTo(Math.round(cx) + 0.5, yOf(g, b[2]));
      ctx.lineTo(Math.round(cx) + 0.5, yOf(g, b[3]));
      ctx.stroke();
      var top = yOf(g, Math.max(b[1], b[4])), bot = yOf(g, Math.min(b[1], b[4]));
      ctx.fillRect(cx - body / 2, top, body, Math.max(1, bot - top));
      if (g.vmax) {
        var vh = (b[5] / g.vmax) * g.volH;
        ctx.globalAlpha = 0.34;
        ctx.fillRect(cx - body / 2, g.volTop + g.volH - vh, body, vh);
        ctx.globalAlpha = 1;
      }
    }

    ctx.strokeStyle = LINE; ctx.beginPath();
    ctx.moveTo(0, Math.round(PADT + g.priceH) + 0.5);
    ctx.lineTo(g.plotW, Math.round(PADT + g.priceH) + 0.5); ctx.stroke();

    if (hover !== null && hover >= 0 && hover < g.bars.length) crosshair(g);
    readout(g);
  }

  function crosshair(g) {
    var b = g.bars[hover], cx = g.step * (hover + 0.5);
    ctx.save();
    ctx.setLineDash([3, 3]); ctx.strokeStyle = MUTE;
    ctx.beginPath(); ctx.moveTo(Math.round(cx) + 0.5, PADT);
    ctx.lineTo(Math.round(cx) + 0.5, PADT + g.priceH + GAPV + g.volH); ctx.stroke();
    var y = yOf(g, b[4]);
    ctx.beginPath(); ctx.moveTo(0, Math.round(y) + 0.5);
    ctx.lineTo(g.plotW, Math.round(y) + 0.5); ctx.stroke();
    ctx.restore();
    // Price tag on the axis, so the crosshair reads like a real terminal.
    var label = fmt(b[4]);
    ctx.fillStyle = INK;
    ctx.fillRect(g.plotW + 4, y - 9, PADR - 6, 18);
    ctx.fillStyle = PAPER; ctx.textAlign = 'left';
    ctx.fillText(label, g.plotW + 9, y);
    var dl = b[0];
    ctx.textAlign = 'center';
    var w = ctx.measureText(dl).width + 12;
    ctx.fillStyle = INK;
    ctx.fillRect(cx - w / 2, H - PADB + 2, w, 17);
    ctx.fillStyle = PAPER;
    ctx.fillText(dl, cx, H - PADB / 2 + 1);
  }

  function readout(g) {
    var i = (hover !== null && hover >= 0 && hover < g.bars.length)
            ? hover : g.bars.length - 1;
    var b = g.bars[i], prev = i > 0 ? g.bars[i - 1][4] : b[1];
    var chg = b[4] - prev, pct = prev ? chg / prev * 100 : 0;
    var col = chg >= 0 ? UP : DOWN;
    read.innerHTML =
      '<b>' + TICKER + '</b>' +
      '<span class="d">' + b[0] + '</span>' +
      '<span>O <i>' + fmt(b[1]) + '</i></span>' +
      '<span>H <i>' + fmt(b[2]) + '</i></span>' +
      '<span>L <i>' + fmt(b[3]) + '</i></span>' +
      '<span>C <i>' + fmt(b[4]) + '</i></span>' +
      '<span style="color:' + col + '">' + (chg >= 0 ? '+' : '') + fmt(chg) +
      ' (' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%)</span>' +
      '<span class="v">Vol <i>' + fmtVol(b[5]) + '</i></span>';
  }

  function at(clientX) {
    var g = geom(), r = cv.getBoundingClientRect();
    var i = Math.floor((clientX - r.left) / g.step);
    return i < 0 ? 0 : i >= g.bars.length ? g.bars.length - 1 : i;
  }

  cv.addEventListener('mousemove', function (e) { hover = at(e.clientX); draw(); });
  cv.addEventListener('mouseleave', function () { hover = null; draw(); });
  cv.addEventListener('touchstart', function (e) {
    hover = at(e.touches[0].clientX); draw();
  }, { passive: true });
  cv.addEventListener('touchmove', function (e) {
    hover = at(e.touches[0].clientX); draw();
  }, { passive: true });

  // Wheel and pinch zoom over the time axis, clamped to the data.
  cv.addEventListener('wheel', function (e) {
    e.preventDefault();
    var n = view.to - view.from;
    var k = e.deltaY > 0 ? 1.12 : 0.89;
    var want = Math.round(n * k);
    want = Math.max(12, Math.min(D.length, want));
    var anchor = view.from + Math.round(n * ((e.clientX - cv.getBoundingClientRect().left) / W));
    var from = Math.round(anchor - (anchor - view.from) * (want / n));
    from = Math.max(0, Math.min(D.length - want, from));
    view = { from: from, to: from + want };
    draw();
  }, { passive: false });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      var g = geom();
      if (hover === null) hover = g.bars.length - 1;
      hover += e.key === 'ArrowRight' ? 1 : -1;
      hover = Math.max(0, Math.min(g.bars.length - 1, hover));
      draw();
    } else if (e.key === '0') { view = { from: 0, to: D.length }; hover = null; draw(); }
  });

  document.getElementById('reset').addEventListener('click', function () {
    view = { from: 0, to: D.length }; hover = null; draw();
  });

  // The backing store must follow the element's real box, not a guess made
  // before layout settles. Sizing on load alone leaves the canvas short (a
  // dead band underneath) or tall (a clipped volume panel), depending on
  // which resolves first. Observing the container catches every change,
  // including the flex layout resolving and the window being dragged.
  if (window.ResizeObserver) {
    new ResizeObserver(resize).observe(cv.parentNode);
  } else {
    window.addEventListener('resize', resize);
    window.addEventListener('load', resize);
  }
  resize();
})();
"""

CHART_CSS = """
  * { box-sizing:border-box; }
  html,body { height:100%; }
  body { margin:0; background:#FFFFFF; color:#0C0D0E;
         font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         display:flex; flex-direction:column; overflow:hidden; }
  header { display:flex; align-items:center; gap:.9rem; flex-wrap:wrap;
           padding:.7rem 1rem; border-bottom:1px solid #E7E6E1; flex:0 0 auto; }
  .home { font-size:.7rem; font-weight:660; letter-spacing:.02em;
          color:#FFFFFF; background:#0C0D0E; padding:.32rem .58rem;
          border-radius:5px; text-decoration:none; }
  #read { display:flex; align-items:baseline; gap:.85rem; flex-wrap:wrap;
          font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
          font-size:.76rem; color:#6E747B; font-variant-numeric:tabular-nums; }
  #read b { font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
            font-size:1rem; font-weight:660; color:#0C0D0E; letter-spacing:-.02em; }
  #read i { font-style:normal; color:#0C0D0E; }
  #read .d { color:#0C0D0E; }
  #hint { margin-left:auto; font-size:.68rem; color:#6E747B; white-space:nowrap; }
  #reset { font:inherit; font-size:.68rem; color:#6E747B; background:#FFFFFF;
           border:1px solid #E7E6E1; border-radius:6px; padding:.26rem .55rem;
           cursor:pointer; }
  #reset:hover { color:#0C0D0E; border-color:#0C0D0E; }
  .wrap { flex:1 1 auto; min-height:0; padding:.5rem .5rem .2rem; }
  canvas { width:100%; height:100%; display:block; touch-action:pan-y; }
  noscript img { max-width:100%; }
  @media (max-width:36rem) {
    header { padding:.5rem .7rem; gap:.5rem; }
    #hint { display:none; }
    #read { font-size:.7rem; gap:.15rem .55rem; }
    #read b { font-size:.9rem; }
    #read .v { display:none; }          /* volume is in the panel already */
    .wrap { padding:.35rem .35rem .15rem; }
  }
"""


def render_html(ticker, rows, csp_hash_fn):
    import json as _json
    bars = _json.dumps([[r[0], r[1], r[2], r[3], r[4], r[5] if len(r) > 5 else 0]
                        for r in rows], separators=(",", ":"))
    boot = (f'window.__TICKER__={_json.dumps(ticker)};'
            f'window.__BARS__={bars};')
    last, first = rows[-1][4], rows[0][4]
    pct = (last / first - 1) * 100 if first else 0
    csp = ("default-src 'none'; "
           f"script-src '{csp_hash_fn(boot)}' '{csp_hash_fn(CHART_JS)}'; "
           f"style-src '{csp_hash_fn(CHART_CSS)}'; "
           "img-src 'self'; base-uri 'none'; form-action 'none'")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{ticker} chart | v2v.investing</title>
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="color-scheme" content="light">
<style>{CHART_CSS}</style>
</head>
<body>
<header>
  <a class="home" href="../index.html">v2v.investing</a>
  <div id="read"></div>
  <span id="hint">drag to read &middot; scroll to zoom &middot; arrows to step</span>
  <button id="reset" type="button">Reset</button>
</header>
<div class="wrap">
  <canvas id="c" aria-label="{ticker} daily candlestick chart, \
{len(rows)} sessions, {rows[0][0]} to {rows[-1][0]}, \
{pct:+.1f} percent over the period"></canvas>
  <noscript><img src="{ticker}.svg" alt="{ticker} daily candles"></noscript>
</div>
<script>{boot}</script>
<script>{CHART_JS}</script>
</body>
</html>
"""


def main():
    demo = "--demo" in sys.argv
    OUT.mkdir(exist_ok=True)
    written, missing = [], []
    for i, t in enumerate(TICKERS):
        if not demo and i:
            # Alpha Vantage's free tier allows 5 calls a minute. Twelve
            # tickers spaced 13s apart stay inside it and still finish in
            # under three minutes, well within the routine's run.
            time.sleep(13)
        rows = demo_rows(i) if demo else fetch_ohlc(t)
        if not rows and not demo:
            rows = cached(t)          # fall back to the last good fetch
        if not rows:
            missing.append(t)
            continue
        if not demo:
            cache_dir().mkdir(parents=True, exist_ok=True)
            (cache_dir() / f"{t}.json").write_text(json.dumps(rows), encoding="utf-8")
        (OUT / f"{t}.svg").write_text(render(t, rows), encoding="utf-8")
        (OUT / f"{t}.html").write_text(
            render_html(t, rows, sha256_src), encoding="utf-8")
        written.append(t)

    (OUT / "index.json").write_text(
        json.dumps({"available": sorted(written), "demo": demo}, indent=1),
        encoding="utf-8")
    print(f"charts: wrote {len(written)}"
          + (f", no data for {', '.join(missing)}" if missing else ""))
    if missing and not written:
        print("no source reachable; build.py will fall back to external charts")


if __name__ == "__main__":
    main()
