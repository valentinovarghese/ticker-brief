#!/usr/bin/env python3
"""Regenerate research.json, the data behind the Earnings section of the site.

Run it before build.py. It is deliberately safe to run every day:

    python3 research.py            # top up the cache, recompute, write research.json
    python3 research.py --offline  # recompute from the cache only, no network
    python3 research.py --backfill # rebuild a ticker's price history from scratch

Nothing here is allowed to break the daily brief. Every network call can fail,
every ticker can be missing, and the worst case is that research.json keeps
yesterday's numbers. The script exits 0 unless the cache is empty enough that
there is nothing to publish at all.

WHAT IS CACHED
    research/sessions/<TICKER>.json   {"YYYY-MM-DD": [open, plus4h, close]}
    research/earnings/<TICKER>.json   the quarterly earnings rows from AlphaVantage
    research/upcoming.json            {"TICKER": {"date": ..., "est": bool}}

The session cache is the expensive part: 30-minute bars back to 2020, reduced
to the three prices per day the study actually reads. Keeping it in the repo
means a daily run needs one small request per ticker instead of six years of
history, and a rate-limited day costs nothing at all.

DEFINITIONS, stated so the numbers can be checked
    open        the open of the 09:30 bar
    plus4h      the close of the 13:00 bar, i.e. the 13:30 print
    close       the close of the last bar of the session
    reaction    the first regular session that OPENS after the release:
                the next trading day for an after-hours report, the same day
                for a pre-market one
    run-up      close N sessions before the reaction, to the last close before
                the news reaches the tape
    base rate   the same measurement over every other stretch of the same
                length for that same stock, which is what stops a stock that
                drifts up anyway from looking like it has an earnings effect
"""
import datetime as dt
import json
import math
import os
import statistics as st
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "research")
SESSIONS = os.path.join(CACHE, "sessions")
EARNINGS = os.path.join(CACHE, "earnings")
UPCOMING = os.path.join(CACHE, "upcoming.json")
OUT = os.path.join(ROOT, "research.json")

TICKERS = ["AAPL", "AMZN", "TSLA", "PLTR", "MSFT", "GOOGL",
           "HOOD", "NVDA", "INTC", "NBIS", "MRVL", "META"]

OPEN_BAR, PLUS4_BAR, LAST_BAR = "09:30:00", "13:00:00", "15:30:00"
START = "2020-01-01"
WINDOWS = (20, 10)          # trading sessions held before the report
MIN_EVENTS = 3              # below this a ticker is not worth ranking

# AlphaVantage free tier allows 25 calls a day and charts.py already spends 12.
# Refreshes are demand-driven, so most days spend none of the remainder, and
# the cap is set low enough that a bad day cannot starve the chart refresh.
AV_BUDGET = 4
TD_SPACING = 8              # seconds; the free key allows 8 requests a minute

log = lambda m: print(m, flush=True)


# ---------------------------------------------------------------- fetching

def get(url, tries=4, timeout=90):
    """A JSON GET that reports failure rather than raising it."""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            # 400 means the symbol did not trade in the window asked for,
            # which is a fact about the ticker, not a failure to retry.
            if e.code == 400:
                return {"status": "error", "message": "no data in range"}
            if attempt == tries - 1:
                return {"status": "error", "message": f"HTTP {e.code}"}
        except Exception as e:
            if attempt == tries - 1:
                return {"status": "error", "message": str(e)[:80]}
        time.sleep(3 * (attempt + 1))


def get_text(url, tries=3, timeout=90):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read().decode()
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(3 * (attempt + 1))


def td_series(ticker, start, end, key):
    """30-minute bars for one date range, with credit-limit backoff."""
    url = (f"https://api.twelvedata.com/time_series?symbol={ticker}"
           f"&interval=30min&start_date={start}&end_date={end}&outputsize=5000"
           f"&timezone=America/New_York&apikey={key}")
    for _ in range(6):
        d = get(url)
        msg = str(d.get("message", "")) if isinstance(d, dict) else ""
        if isinstance(d, dict) and d.get("status") == "error" and "credit" in msg.lower():
            time.sleep(20)
            continue
        return d
    return {"status": "error", "message": "credits"}


# ---------------------------------------------------------------- session cache

def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj, indent=None):
    """Write via a temporary file so an interrupted run cannot truncate a cache."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=indent, separators=(",", ":") if indent is None else None)
    os.replace(tmp, path)


def fold(values, today):
    """30-minute bars to one row per session: [open, plus4h, close].

    A session is kept once it has both legs of the measurement. Today is held
    back until the 15:30 bar exists, because a session still trading has no
    close and would poison every base rate that reads one.
    """
    by = {}
    for stamp, bar in values.items():
        by.setdefault(stamp[:10], {})[stamp[11:]] = bar
    out = {}
    for day, bars in by.items():
        if OPEN_BAR not in bars or PLUS4_BAR not in bars:
            continue
        if day >= today and LAST_BAR not in bars:
            continue
        out[day] = [bars[OPEN_BAR][0], bars[PLUS4_BAR][3], bars[max(bars)][3]]
    return out


def et_today():
    """The date in New York, which is the date the market trades on."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return (dt.datetime.utcnow() - dt.timedelta(hours=5)).date().isoformat()


def refresh_sessions(key, backfill=False):
    """Top up each ticker's session cache. Missing history is backfilled."""
    today = et_today()
    for ticker in TICKERS:
        path = os.path.join(SESSIONS, f"{ticker}.json")
        have = read_json(path, {})

        if backfill or not have:
            log(f"  {ticker}: backfilling from {START}")
            raw = {}
            for year in range(int(START[:4]), int(today[:4]) + 1):
                d = td_series(ticker, f"{year}-01-01", f"{year + 1}-01-01", key)
                if isinstance(d, dict) and d.get("values"):
                    for v in d["values"]:
                        raw[v["datetime"]] = [float(v["open"]), float(v["high"]),
                                              float(v["low"]), float(v["close"])]
                else:
                    log(f"    {year}: {str(d.get('message', 'no values'))[:60]}")
                time.sleep(TD_SPACING)
            have.update(fold(raw, today))
        else:
            # Only the tail is ever new. Six weeks covers a long holiday plus
            # any run that was skipped, and still fits one request.
            start = (dt.date.fromisoformat(max(have)) - dt.timedelta(days=42)).isoformat()
            d = td_series(ticker, start, today, key)
            if isinstance(d, dict) and d.get("values"):
                raw = {v["datetime"]: [float(v["open"]), float(v["high"]),
                                       float(v["low"]), float(v["close"])]
                       for v in d["values"]}
                have.update(fold(raw, today))
            else:
                log(f"  {ticker}: no update ({str(d.get('message', '?'))[:50]}), cache kept")
            time.sleep(TD_SPACING)

        if have:
            write_json(path, {d: have[d] for d in sorted(have)})
            days = sorted(have)
            log(f"  {ticker}: {len(days)} sessions, {days[0]} to {days[-1]}")


# ---------------------------------------------------------------- earnings cache

def load_earnings():
    return {t: read_json(os.path.join(EARNINGS, f"{t}.json"), []) for t in TICKERS}


def refresh_earnings(key, earn, sess):
    """Refetch a ticker's earnings only when a report is actually due.

    A quarterly calendar changes four times a year. Asking daily would spend
    the whole AlphaVantage allowance to learn nothing, so a ticker is refreshed
    only when its expected next report date has passed without arriving.
    """
    today = et_today()
    upcoming = read_json(UPCOMING, {})
    spent = 0

    for ticker in TICKERS:
        rows = earn.get(ticker) or []
        newest = max((r.get("reportedDate", "") for r in rows), default="")
        expected = (upcoming.get(ticker) or {}).get("date", "")
        due = (not rows) or (expected and expected <= today and newest < expected)
        if not due or spent >= AV_BUDGET:
            continue

        d = get(f"https://www.alphavantage.co/query?function=EARNINGS"
                f"&symbol={ticker}&apikey={key}")
        spent += 1
        quarters = d.get("quarterlyEarnings") if isinstance(d, dict) else None
        if not quarters:
            log(f"  {ticker}: earnings refresh failed ({str(d)[:70]}), cache kept")
            continue
        fresh = [r for r in quarters if r.get("reportedDate", "") >= START]
        write_json(os.path.join(EARNINGS, f"{ticker}.json"), fresh, indent=1)
        earn[ticker] = fresh
        log(f"  {ticker}: {len(fresh)} reports, newest {fresh[0]['reportedDate']}")
        time.sleep(1)

    refresh_upcoming(key, earn, upcoming, today, AV_BUDGET - spent)
    return earn


def refresh_upcoming(key, earn, upcoming, today, budget):
    """Next report date per ticker, from the calendar where it is published.

    Where it is not, a date is projected from the same quarter a year ago,
    which these twelve companies keep to within a few days. A projected date
    is flagged so the page can say so rather than implying a confirmed one.

    The calendar only publishes three months ahead, so the nearest reports are
    asked about first and the far ones are not asked about at all. That keeps
    the daily cost at a call or two, and spends it where a confirmed date is
    worth having.
    """
    horizon = (dt.date.fromisoformat(today) + dt.timedelta(days=88)).isoformat()

    def due(ticker):
        known = upcoming.get(ticker) or {}
        return known.get("date") or (project(earn.get(ticker) or [], today) or {}).get("date") or "9999"

    for ticker in sorted(TICKERS, key=due):
        known = upcoming.get(ticker) or {}
        if known.get("date", "") > today and not known.get("est"):
            continue
        got = None
        if budget > 0 and due(ticker) <= horizon:
            csv = get_text(f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR"
                           f"&symbol={ticker}&horizon=3month&apikey={key}")
            budget -= 1
            if csv and "reportDate" in csv:
                for line in csv.strip().splitlines()[1:]:
                    parts = line.split(",")
                    if len(parts) > 2 and parts[0] == ticker and parts[2] > today:
                        got = {"date": parts[2], "est": False,
                               "when": parts[6] if len(parts) > 6 else ""}
                        break
            time.sleep(1)
        if not got:
            got = project(earn.get(ticker) or [], today)
        if got:
            upcoming[ticker] = got
    write_json(UPCOMING, upcoming, indent=1)
    return upcoming


def project(rows, today):
    """A report date a year on from the same fiscal quarter, rounded to a weekday."""
    dates = sorted(r["reportedDate"] for r in rows if r.get("reportedDate"))
    if len(dates) < 5:
        return None
    for past in dates:
        guess = dt.date.fromisoformat(past) + dt.timedelta(days=364)
        if guess.isoformat() > today:
            while guess.weekday() > 4:
                guess += dt.timedelta(days=1)
            return {"date": guess.isoformat(), "est": True}
    return None


# ---------------------------------------------------------------- statistics

def median(v):
    return st.median(v)


def hitrate(v):
    return 100 * sum(1 for x in v if x > 0) / len(v)


def longest_run(flags):
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


def binom_p(hits, n, prob):
    """One-sided: the chance of this many up quarters or more, if the stock were
    only doing what it usually does. Exact, because n is small enough to sum."""
    prob = min(max(prob, 1e-9), 1 - 1e-9)
    return sum(math.comb(n, k) * prob ** k * (1 - prob) ** (n - k)
               for k in range(hits, n + 1))


def welch_t(sample, base):
    """How far the earnings sample sits from the stock's ordinary behaviour,
    in standard errors of the sample."""
    if len(sample) < 2:
        return 0.0
    sd = st.stdev(sample)
    if sd == 0:
        return 0.0
    return (st.mean(sample) - st.mean(base)) / (sd / math.sqrt(len(sample)))


# ---------------------------------------------------------------- the studies

def build_events(sess, earn):
    """One row per report: where the reaction session is, and what it did."""
    rows = []
    for ticker in TICKERS:
        days = sorted(sess.get(ticker) or {})
        if not days:
            continue
        s = sess[ticker]
        index = {d: i for i, d in enumerate(days)}
        for e in earn.get(ticker) or []:
            reported = e.get("reportedDate")
            when = (e.get("reportTime") or "").lower()
            if not reported or reported < START:
                continue
            # Pre-market lands on the same day; anything else on the next open.
            candidates = ([d for d in days if d >= reported] if "pre" in when
                          else [d for d in days if d > reported])
            if not candidates:
                continue
            reaction = candidates[0]
            # AlphaVantage carries quarters from before a ticker traded, from
            # the Yandex era of NBIS and the pre-IPO years of HOOD and PLTR.
            # Without this guard the first session absorbs all of them.
            if (dt.date.fromisoformat(reaction)
                    - dt.date.fromisoformat(reported)).days > 5:
                continue
            i = index[reaction]
            o, p4, c = s[reaction]
            prior = s[days[i - 1]][2] if i > 0 else None
            try:
                surprise = float(e.get("surprisePercentage"))
            except (TypeError, ValueError):
                surprise = None
            rows.append({
                "ticker": ticker, "reportedDate": reported, "reactionDay": reaction,
                "surprise": surprise, "beat": surprise is not None and surprise > 0,
                "target": 100 * (p4 / o - 1),
                "session": 100 * (c / o - 1),
                "gap": 100 * (o / prior - 1) if prior else None,
            })
    rows.sort(key=lambda r: (r["ticker"], r["reportedDate"]))
    return rows


def before_study(sess, events, n):
    """Hold from the close n sessions before the report to the last close
    before the news lands. Everything is scored against the same stock's own
    record over every other n-session stretch it has traded."""
    out = {}
    for ticker in TICKERS:
        days = sorted(sess.get(ticker) or {})
        if len(days) <= n + 2:
            continue
        close = {d: sess[ticker][d][2] for d in days}
        index = {d: i for i, d in enumerate(days)}
        base = [100 * (close[days[i]] / close[days[i - n]] - 1)
                for i in range(n, len(days))]
        base_day = [100 * (close[days[i]] / close[days[i - 1]] - 1)
                    for i in range(1, len(days))]

        runups, lastdays, dips, dates = [], [], [], []
        for r in sorted((r for r in events if r["ticker"] == ticker),
                        key=lambda r: r["reactionDay"]):
            i = index.get(r["reactionDay"])
            if i is None or i - 1 - n < 0:
                continue
            path = [close[d] for d in days[i - 1 - n:i]]
            entry = path[0]
            runups.append(round(100 * (path[-1] / entry - 1), 3))
            lastdays.append(100 * (path[-1] / path[-2] - 1))
            peak, worst = entry, 0.0
            for price in path[1:]:
                peak = max(peak, price)
                worst = min(worst, 100 * (price / peak - 1))
            dips.append(worst)
            dates.append(r["reactionDay"])

        if len(runups) < MIN_EVENTS:
            continue
        up = [x > 0 for x in runups]
        quartiles = st.quantiles(runups, n=4)
        out[ticker] = {
            "n": len(runups),
            "median": round(median(runups), 2),
            "edge": round(median(runups) - median(base), 2),
            "hit": round(hitrate(runups), 1),
            "baseHit": round(hitrate(base), 1),
            "last8": round(100 * sum(up[-8:]) / len(up[-8:]), 1),
            "streak": longest_run(up),
            "q1": round(quartiles[0], 2),
            "worst": round(min(runups), 2),
            "mdd": round(median(dips), 2),
            "lastdayMed": round(median(lastdays), 2),
            "lastdayNeg": round(100 * sum(1 for x in lastdays if x < 0) / len(lastdays), 1),
            "lastdayBase": round(100 * sum(1 for x in base_day if x < 0) / len(base_day), 1),
            "p": round(binom_p(sum(up), len(up), hitrate(base) / 100), 4),
            "ev": runups,
            "first": dates[0][:7],
            "last": dates[-1][:7],
        }
    return out


def eve_pooled(sess, events):
    """The final session before a report, pooled across every stock."""
    moves, base = [], []
    for ticker in TICKERS:
        days = sorted(sess.get(ticker) or {})
        if len(days) < 3:
            continue
        close = {d: sess[ticker][d][2] for d in days}
        index = {d: i for i, d in enumerate(days)}
        base += [100 * (close[days[i]] / close[days[i - 1]] - 1)
                 for i in range(1, len(days))]
        for r in events:
            if r["ticker"] != ticker:
                continue
            i = index.get(r["reactionDay"])
            if i is None or i < 2:
                continue
            moves.append(100 * (close[days[i - 1]] / close[days[i - 2]] - 1))
    if not moves:
        return None
    return {"n": len(moves), "median": round(median(moves), 2),
            "neg": round(100 * sum(1 for x in moves if x < 0) / len(moves), 1),
            "baseNeg": round(100 * sum(1 for x in base if x < 0) / len(base), 1)}


def seg(label, rows):
    v = [r["target"] for r in rows]
    if not v:
        return None
    return {"label": label, "n": len(v), "median": round(median(v), 3),
            "mean": round(st.mean(v), 3), "hit": round(hitrate(v), 1),
            "best": round(max(v), 2), "worst": round(min(v), 2)}


def after_study(sess, events):
    """From the opening bell of the reaction session to four hours later."""
    ev = [r for r in events if r["gap"] is not None]
    beats = [r for r in ev if r["beat"]]
    misses = [r for r in ev if r["surprise"] is not None and r["surprise"] < 0]
    inline = [r for r in ev if r["surprise"] is not None and r["surprise"] == 0]

    segments = [s for s in (
        seg("All earnings events", ev),
        seg("EPS beats", beats),
        seg("EPS beat and gapped up", [r for r in beats if r["gap"] > 0]),
        seg("EPS beat but gapped down", [r for r in beats if r["gap"] <= 0]),
        seg("EPS miss or inline", [r for r in ev if not r["beat"]]),
    ) if s]

    def bucket(rows, edges):
        out = []
        for label, test in edges:
            v = [r["target"] for r in rows if test(r["gap"])]
            if v:
                out.append({"label": label, "n": len(v),
                            "median": round(median(v), 3),
                            "mean": round(st.mean(v), 3),
                            "hit": round(hitrate(v), 1),
                            "best": round(max(v), 2), "worst": round(min(v), 2)})
        return out

    beat_buckets = bucket(beats, [
        ("Gapped down", lambda g: g < 0),
        ("Gap 0 to 3%", lambda g: 0 <= g < 3),
        ("Gap 3 to 8%", lambda g: 3 <= g < 8),
        ("Gap over 8%", lambda g: g >= 8),
    ])
    miss_buckets = bucket(misses, [
        ("Down over 8%", lambda g: g <= -8),
        ("Down 0 to 8%", lambda g: -8 < g < 0),
        ("Up 0 to 8%", lambda g: 0 <= g < 8),
        ("Up over 8%", lambda g: g >= 8),
    ])

    # A ticker's base rate excludes its own earnings days, so the comparison
    # is against ordinary trading rather than against a set containing itself.
    per_beat, per_miss = {}, {}
    for ticker in TICKERS:
        days = sorted(sess.get(ticker) or {})
        if not days:
            continue
        event_days = {r["reactionDay"] for r in events if r["ticker"] == ticker}
        base = [100 * (sess[ticker][d][1] / sess[ticker][d][0] - 1)
                for d in days if d not in event_days]
        if not base:
            continue
        rows = [r for r in beats if r["ticker"] == ticker]
        if rows:
            v = [r["target"] for r in rows]
            per_beat[ticker] = {
                "n": len(v), "median": round(median(v), 3), "hit": round(hitrate(v), 1),
                "baseHit": round(hitrate(base), 1), "t": round(welch_t(v, base), 2),
                "gapMed": round(median([r["gap"] for r in rows]), 2),
            }
        rows = [r for r in misses if r["ticker"] == ticker]
        if rows:
            v = [r["target"] for r in rows]
            per_miss[ticker] = {"n": len(v), "median": round(median(v), 3),
                                "hit": round(hitrate(v), 1)}

    pooled = None
    if misses:
        v = [r["target"] for r in misses]
        pooled = {"n": len(v), "median": round(median(v), 2),
                  "hit": round(hitrate(v), 1),
                  "gapMed": round(median([r["gap"] for r in misses]), 2)}
    inline_stats = None
    if inline:
        v = [r["target"] for r in inline]
        inline_stats = {"n": len(v), "median": round(median(v), 2),
                        "hit": round(hitrate(v), 1)}

    return {
        "segments": segments,
        "beatBuckets": beat_buckets,
        "missBuckets": miss_buckets,
        "perTickerBeat": per_beat,
        "perTickerMiss": per_miss,
        "missPooled": pooled,
        "inline": inline_stats,
        "beatGapMed": round(median([r["gap"] for r in beats]), 2) if beats else 0.0,
    }


def upcoming_study(sess, before, upcoming, today):
    """Which stocks are inside the window the study describes, right now.

    Sessions are counted rather than days, because the study holds for twenty
    trading sessions and a fortnight of calendar time is not the same thing.
    """
    out = []
    for ticker in TICKERS:
        entry = upcoming.get(ticker) or {}
        date = entry.get("date")
        if not date or date < today:
            continue
        days = sorted(sess.get(ticker) or {})
        if not days:
            continue
        # Trading sessions between now and the report, weekends removed. It
        # ignores market holidays, so it can read one session long across one.
        start = dt.date.fromisoformat(max(days[-1], today))
        end = dt.date.fromisoformat(date)
        sessions = sum(1 for i in range((end - start).days)
                       if (start + dt.timedelta(days=i + 1)).weekday() < 5)
        stats = (before.get(ticker) or {})
        out.append({
            "ticker": ticker,
            "date": date,
            "est": bool(entry.get("est")),
            "when": entry.get("when", ""),
            "days": (end - dt.date.fromisoformat(today)).days,
            "sessions": sessions,
            "open": sessions <= WINDOWS[0],
            "median": stats.get("median"),
            "hit": stats.get("hit"),
            "baseHit": stats.get("baseHit"),
            "mdd": stats.get("mdd"),
            "p": stats.get("p"),
            "n": stats.get("n"),
        })
    out.sort(key=lambda r: r["date"])
    return out


# ---------------------------------------------------------------- assembly

def compute(sess, earn, upcoming, today):
    events = build_events(sess, earn)
    if not events:
        sys.exit("research.py: no earnings events could be located, nothing written")
    before = {f"w{n}": before_study(sess, events, n) for n in WINDOWS}
    per_ticker = {t: len(sess.get(t) or {}) for t in TICKERS if sess.get(t)}
    covered = sorted(d for t in per_ticker for d in sess[t])
    return {
        "generated": today,
        "before": before,
        "eve": eve_pooled(sess, events),
        "after": after_study(sess, events),
        "upcoming": upcoming_study(sess, before[f"w{WINDOWS[0]}"], upcoming, today),
        "meta": {
            "tickers": len(per_ticker),
            "sessions": sum(per_ticker.values()),
            "sessionsEach": round(st.mean(list(per_ticker.values()))) if per_ticker else 0,
            "events": len(events),
            "firstDate": covered[0] if covered else None,
            "lastDate": covered[-1] if covered else None,
            "windows": list(WINDOWS),
        },
    }


def main():
    offline = "--offline" in sys.argv
    backfill = "--backfill" in sys.argv
    av = os.environ.get("ALPHAVANTAGE_KEY", "").strip().strip(".")
    td = os.environ.get("TWELVEDATA_KEY", "").strip().strip(".")
    today = et_today()

    if not offline and td:
        log("prices:")
        refresh_sessions(td, backfill=backfill)
    elif not offline:
        log("prices: TWELVEDATA_KEY not set, using the cache")

    sess = {t: read_json(os.path.join(SESSIONS, f"{t}.json"), {}) for t in TICKERS}
    sess = {t: v for t, v in sess.items() if v}
    if not sess:
        sys.exit("research.py: no price cache and no key to build one, nothing written")

    earn = load_earnings()
    if not offline and av:
        log("earnings:")
        earn = refresh_earnings(av, earn, sess)
    upcoming = read_json(UPCOMING, {})

    data = compute(sess, earn, upcoming, today)
    write_json(OUT, data, indent=None)

    m = data["meta"]
    log(f"research.json: {m['events']} reports over {m['sessions']} sessions, "
        f"{m['firstDate']} to {m['lastDate']}")
    soon = [u for u in data["upcoming"] if u["open"]]
    if soon:
        log("in the window now: " + ", ".join(
            f"{u['ticker']} {u['date']} ({u['sessions']} sessions)" for u in soon))


if __name__ == "__main__":
    main()
