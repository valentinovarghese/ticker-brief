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
                     float(bar["3. low"]), float(bar["4. close"])))
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
                         float(parts[3]), float(parts[4])))
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
        rows.append((f"day{i}", o, h, lo, c))
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

    for i, (_, o, h, l, c) in enumerate(rows):
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
