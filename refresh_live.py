"""Refresh validated chart data; render cached charts without network on --render."""
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import charts

def valid(rows):
    if not rows:
        raise ValueError("Provider returned no bars")
    previous = ""
    for r in rows:
        datetime.fromisoformat(r[0])
        if r[0] <= previous or len(r) != 6:
            raise ValueError("Unordered or malformed bars")
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in r[1:]):
            raise ValueError("Non-numeric price")
        if min(r[1:5]) <= 0 or r[5] < 0 or r[2] < max(r[1],r[3],r[4]) or r[3] > min(r[1],r[4]):
            raise ValueError("Invalid OHLC range")
        previous = r[0]
    return rows

def render():
    for ticker in charts.TICKERS:
        series = charts.cached(ticker)
        if not series:
            raise ValueError("Missing cache: " + ticker)
        (charts.OUT / (ticker + ".html")).write_text(charts.render_html(ticker, series, charts.sha256_src), encoding="utf-8")

def refresh():
    if not __import__("os").environ.get("TWELVEDATA_KEY"):
        raise SystemExit("TWELVEDATA_KEY is missing")
    out = charts.OUT / "live"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    staged = {}
    # Twelve symbols every ten minutes during the US session: at most 648
    # intraday credits/day. Daily bars are fetched once per UTC date.
    for ticker in charts.TICKERS:
        rows = valid(charts._from_twelvedata(ticker, "1min"))
        time.sleep(9)
        series = charts.cached(ticker) or {}
        for label, minutes, keep in [("1m",1,390),("3m",3,440),("5m",5,470),("15m",15,440),("30m",30,400),("1h",60,420)]:
            series[label] = rows[-keep:] if minutes == 1 else charts.aggregate(rows, minutes)[-keep:]
        target = out / (ticker + ".json")
        previous = json.loads(target.read_text()) if target.exists() else {}
        daily_checked = previous.get("daily_checked", "")
        if daily_checked != stamp[:10]:
            daily = valid(charts._from_twelvedata(ticker, "1day"))
            series["1D"] = charts.drop_incomplete(daily)[-charts.SESSIONS:]
            daily_checked = stamp[:10]
            time.sleep(9)
        staged[ticker] = dict(ticker=ticker, checked=stamp, updated=rows[-1][0], daily_checked=daily_checked, series=series)
    # No files change until every ticker has valid source data.
    for ticker, payload in staged.items():
        (out / (ticker + ".json")).write_text(json.dumps(payload, separators=(",",":")), encoding="utf-8")
        (charts.cache_dir() / (ticker + ".json")).write_text(json.dumps(payload["series"]), encoding="utf-8")
    render()
    print("Updated all 12 chart series")

if __name__ == "__main__":
    render() if "--render" in sys.argv else refresh()


