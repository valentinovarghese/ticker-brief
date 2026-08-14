#!/usr/bin/env python3
"""Fetch recent per-ticker news, score it for materiality, write news/index.json.

    python3 news.py              # fetch, score, write news/index.json
    python3 news.py --dry-run    # fetch and print, write nothing
    python3 news.py --selftest   # score fixtures offline, no network

WHY THIS SHAPE

GitHub Pages serves static files. Nothing on the published page can poll a
news API, so "live" here means: a scheduled job fetches, commits the result,
and the page re-reads that file every few minutes. This script is the fetch
half. `.github/workflows/news.yml` runs it and commits only when the content
actually changes.

WHAT COUNTS AS NEWS

The brief's own rule is that an item must be concrete and dated: earnings and
guidance, SEC filings, M&A, issuance, buybacks, dividends, contracts with
dollar values, regulatory and legal actions. Price targets, "should you buy"
pieces and listicles are excluded by design. The same rule is applied here by
scoring headlines against those categories, so the feed stays closer to a
filings wire than to a stock-message board.

That scoring is a keyword heuristic, not judgement, and the page says so.
It is deliberately tuned to be strict: a missed headline is recoverable, a
feed full of "3 Reasons NVDA Could Double" is not worth checking at all.

SOURCES, both keyless so the workflow needs no secrets

    SEC EDGAR   per-company atom feed. Primary, dated, unambiguous. Every
                filing is kept regardless of score: an 8-K is material by
                construction. Requires a declared User-Agent.
    Google News per-ticker RSS. Broad coverage, used for everything that
                reaches the tape before it reaches EDGAR.

Both are blocked by the sandbox proxy this repo is usually edited from, and
neither is blocked on a GitHub Actions runner. That is why the fetch lives in
the workflow and why --selftest exists: the parsing and scoring can be checked
anywhere, the network cannot.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "news" / "index.json"

TICKERS = ["AAPL", "AMZN", "TSLA", "PLTR", "MSFT", "GOOGL",
           "HOOD", "NVDA", "INTC", "NBIS", "MRVL", "META"]

NAMES = {
    "AAPL": "Apple", "AMZN": "Amazon", "TSLA": "Tesla",
    "PLTR": "Palantir", "MSFT": "Microsoft", "GOOGL": "Alphabet",
    "HOOD": "Robinhood", "NVDA": "Nvidia", "INTC": "Intel",
    "NBIS": "Nebius", "MRVL": "Marvell", "META": "Meta Platforms",
}

# SEC central index keys. Wrong CIK means a silently empty filings feed, so
# these are the numbers that appear in each company's own EDGAR URLs.
CIK = {
    "AAPL": "0000320193", "AMZN": "0001018724", "TSLA": "0001318605",
    "PLTR": "0001321655", "MSFT": "0000789019", "GOOGL": "0001652044",
    "HOOD": "0001783879", "NVDA": "0001045810", "INTC": "0000050863",
    "NBIS": "0001513845", "MRVL": "0001835632", "META": "0001326801",
}

UA = "ticker-brief/1.0 (+https://github.com/valentinovarghese/ticker-brief)"

# How far back an item may be and still count as current.
NEWS_WINDOW = timedelta(hours=48)
FILING_WINDOW = timedelta(days=7)
KEEP_PER_TICKER = 10

# ---------------------------------------------------------------------------
# Materiality
#
# Weights are coarse on purpose. The job is to sort a filing above a feature
# and a feature above a listicle, not to grade twenty shades of relevance.
# ---------------------------------------------------------------------------

CATEGORIES = [
    # "reports"/"operating data" matter: Robinhood's monthly metrics release
    # is exactly the kind of scheduled, numeric disclosure this feed is for.
    ("earnings",   6, r"\b(earnings|results|revenue|eps|guidance|forecast|outlook|"
                      r"quarterly|q[1-4]\s*(?:20\d\d|fy)|beats?|misses?|"
                      r"reports?|reported|operating data|monthly metrics|"
                      r"deliveries|shipments|pre-?announce)\b"),
    ("filing",     6, r"\b(8-k|10-k|10-q|13-?[dgf]|form 4|s-1|6-k|proxy|"
                      r"prospectus|sec filing)\b"),
    ("legal",      5, r"\b(lawsuit|sues?|sued|settle(?:s|d|ment)?|antitrust|doj|"
                      r"ftc|sec (?:probe|investigat|charge)|subpoena|injunction|"
                      r"contempt|appeal|court|judge|ruling|fine[ds]?|penalty|"
                      r"regulator|investigation)\b"),
    ("capital",    5, r"\b(buyback|repurchase|dividend|offering|issuance|notes|"
                      r"debt|convertible|stake|spin-?off|split)\b"),
    ("ma",         5, r"\b(acquir\w+|acquisition|merger|takeover|buys?|"
                      r"divest\w*|sells? (?:its|unit|division))\b"),
    ("contract",   5, r"\b(contract|deal|agreement|award(?:ed|s)?|order|"
                      r"partnership|supply)\b"),
    ("operations", 5, r"\b(recalls?|recalled|halts?|halted|outage|breach|hack|"
                      r"layoffs?|cuts? \d+|shutdown|delays?|delayed|"
                      r"plant|factory|fab|production)\b"),
    # A job title alone is not news. Only an actual change of who holds it is,
    # which is why "Nvidia CEO spotted in Taipei" must not score here.
    ("leadership", 5, r"\b(resign\w*|steps? down|stepping down|departs?|"
                      r"departure|ousted|fired|appoints?|appointed|"
                      r"succeeds?|named (?:ceo|cfo|chair))\b"),
    ("policy",     4, r"\b(tariff|sanction|export (?:ban|control|licen)|"
                      r"ban(?:s|ned)?|approval|approves?|antitrust|"
                      r"national security)\b"),
]

# Coverage that is opinion, promotion or ranking. Excluded by design, the
# same way the brief excludes it.
NOISE = re.compile(
    r"(price target|should you buy|is it too late|best stocks?|top \d+ stocks?|"
    r"\b\d+ (?:reasons?|things|stocks?)\b|motley fool|zacks|prediction|"
    r"here'?s why you|could (?:double|soar|explode)|millionaire|"
    r"better buy|vs\.?\s|analyst[s]? say|rated? (?:buy|sell|hold)|"
    r"my top|i'?m buying|dividend king|if you'?d invested|stock split soon)",
    re.I)

NEGATIVE = re.compile(
    r"\b(fall\w*|drop\w*|plunge\w*|slump\w*|sink\w*|tumbl\w*|slide\w*|"
    r"miss(?:es|ed)?|cuts?|cut|lower\w*|warn\w*|weak\w*|loss(?:es)?|"
    r"lose[sd]?|lost|probe|investigat\w*|sues?|sued|lawsuit|recalls?|"
    r"recalled|halt\w*|ban\w*|delay\w*|layoffs?|resign\w*|steps? down|"
    r"ousted|fired|denies|denied|rejects?|rejected|blocks?|breach|"
    r"downgrade\w*|contempt|fine[ds]?|penalty|shortfall|slowdown|"
    r"decline\w*)\b", re.I)

POSITIVE = re.compile(
    r"\b(beat\w*|top(?:s|ped)|rais\w*|surge\w*|jump\w*|soar\w*|climb\w*|"
    r"rally|record|win[s]?|won|award\w*|approv\w*|upgrade\w*|expand\w*|"
    r"launch\w*|secure[sd]?|signs?|signed|strong\w*|growth|accelerat\w*)\b",
    re.I)

MONEY = re.compile(r"\$\s?\d[\d,.]*\s?(?:billion|bn|million|m\b|trillion|tn)?", re.I)

MIN_SCORE = 5


def score(title):
    """Return (score, [categories], direction) for a headline.

    A headline that trips the noise filter scores zero and is dropped, however
    many category words it also contains: "3 Reasons Nvidia Earnings Could
    Soar" is a listicle that happens to say earnings.
    """
    if NOISE.search(title):
        return 0, [], "neutral"

    total, hit = 0, []
    for name, weight, pattern in CATEGORIES:
        if re.search(pattern, title, re.I):
            total += weight
            hit.append(name)

    # A concrete dollar figure is the single best signal that a headline
    # carries a fact rather than a view.
    if MONEY.search(title):
        total += 3

    neg, pos = len(NEGATIVE.findall(title)), len(POSITIVE.findall(title))
    direction = "negative" if neg > pos else "positive" if pos > neg else "neutral"
    return total, hit, direction


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def get(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_dt(raw):
    """RSS and Atom disagree about time formats. Accept both, fail soft."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:  # "2026-08-14T11:02:00-04:00" with a colon in the offset
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def strip_tags(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def tag(el):
    return el.tag.split("}")[-1]


def parse_feed(xml_bytes):
    """Yield {title, link, published, source} from an RSS 2.0 or Atom document."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    items = []
    for el in root.iter():
        if tag(el) not in ("item", "entry"):
            continue
        rec = {"title": "", "link": "", "published": None, "source": ""}
        for child in el:
            t, text = tag(child), (child.text or "").strip()
            if t == "title":
                rec["title"] = strip_tags(text)
            elif t == "link":
                rec["link"] = child.get("href") or text
            elif t in ("pubDate", "published", "updated") and not rec["published"]:
                rec["published"] = parse_dt(text)
            elif t == "source":
                rec["source"] = strip_tags(text)
            elif t == "category" and not rec["source"]:
                rec["source"] = child.get("term") or ""
        if rec["title"]:
            items.append(rec)
    return items


def google_news(ticker):
    """Company news, excluding the sites that only publish ranking pieces."""
    q = f'"{NAMES[ticker]}" OR "{ticker}" stock when:2d'
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(q)
           + "&hl=en-US&gl=US&ceid=US:en")
    out = []
    for rec in parse_feed(get(url)):
        title, source = rec["title"], rec["source"]
        # Google appends " - Publisher" to every headline, and also supplies
        # the publisher in <source>. Strip the suffix in both cases, so the
        # name is not printed twice on the page.
        if " - " in title:
            head, tail = title.rsplit(" - ", 1)
            if not source or tail.strip().lower() == source.strip().lower():
                title, source = head, source or tail
        out.append({"title": title.strip(), "link": rec["link"],
                    "published": rec["published"],
                    "source": source.strip() or "Google News",
                    "primary": False})
    return out


def sec_filings(ticker):
    """Every filing this company has made recently, newest first."""
    cik = CIK.get(ticker)
    if not cik:
        return []
    url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
           f"&CIK={cik}&type=&dateb=&owner=include&count=20&output=atom")
    out = []
    for rec in parse_feed(get(url)):
        title = rec["title"]
        # EDGAR titles read "8-K - Current report ... (Filer)".
        form = title.split(" - ")[0].strip()
        out.append({"title": f"{form} filed with the SEC",
                    "detail": title,
                    "link": rec["link"],
                    "published": rec["published"],
                    "source": "SEC EDGAR",
                    "primary": True})
    return out


def key(item):
    """Identity of a story, so the same headline from two wires collapses."""
    norm = re.sub(r"[^a-z0-9 ]", "", item["title"].lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def collect(ticker, now):
    """All sources for one ticker, scored, filtered, deduped, newest first."""
    items, errors = [], []

    for label, fn, window in (("sec", sec_filings, FILING_WINDOW),
                              ("news", google_news, NEWS_WINDOW)):
        try:
            fetched = fn(ticker)
        except Exception as e:
            errors.append(f"{label}: {type(e).__name__}")
            continue

        for rec in fetched:
            when = rec.get("published")
            if when and now - when > window:
                continue
            s, cats, direction = score(rec["title"] + " " + rec.get("detail", ""))
            # A filing is material by construction, whatever its title says.
            if rec["primary"]:
                s = max(s, MIN_SCORE + 3)
                if "filing" not in cats:
                    cats.append("filing")
            elif s < MIN_SCORE:
                continue
            items.append({
                "id": key(rec),
                "title": rec["title"][:260],
                "link": rec["link"][:500],
                "source": rec["source"][:80],
                "published": when.astimezone(timezone.utc).isoformat(
                    timespec="minutes") if when else None,
                "score": s,
                "tags": cats[:3],
                "direction": direction,
                "primary": rec["primary"],
            })

    seen, unique = set(), []
    for it in sorted(items, key=lambda i: (-i["score"], i["published"] or "")):
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        unique.append(it)

    unique.sort(key=lambda i: (i["published"] or "", i["score"]), reverse=True)
    return unique[:KEEP_PER_TICKER], errors


def main():
    now = datetime.now(timezone.utc)
    dry = "--dry-run" in sys.argv

    payload = {"fetched": now.isoformat(timespec="seconds"),
               "window_hours": int(NEWS_WINDOW.total_seconds() // 3600),
               "tickers": {}, "errors": {}}

    total, failed = 0, 0
    for i, ticker in enumerate(TICKERS):
        try:
            items, errors = collect(ticker, now)
        except Exception as e:                       # never let one name stop the run
            items, errors = [], [f"collect: {type(e).__name__}"]
        if errors and not items:
            failed += 1
        payload["tickers"][ticker] = items
        if errors:
            payload["errors"][ticker] = errors
        total += len(items)
        print(f"  {ticker:6} {len(items):2d} item(s)"
              + (f"  [{'; '.join(errors)}]" if errors else ""))
        if i < len(TICKERS) - 1:
            time.sleep(1.0)                          # be polite to both sources

    payload["count"] = total
    print(f"news: {total} item(s) across {len(TICKERS)} tickers, "
          f"{failed} ticker(s) with no source reachable")

    if dry:
        print(json.dumps(payload, indent=1)[:2000])
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")

    # Every source failing usually means egress is blocked, not that the news
    # stopped. Say so loudly and leave the previous file to stand.
    if failed == len(TICKERS):
        print("news: NO SOURCE REACHABLE for any ticker")
        return 1
    return 0


# ---------------------------------------------------------------------------

FIXTURES = [
    # (headline, should_publish, expected direction)
    ("Nvidia Announces Financial Results for Second Quarter Fiscal 2027", True, "neutral"),
    ("Intel prices $20 billion stock offering at $95 per share", True, "neutral"),
    ("Apple loses Supreme Court bid to pause App Store commission ruling", True, "negative"),
    ("Tesla recalls 12,000 vehicles over steering fault", True, "negative"),
    ("Meta signs national labor agreement for AI data center construction", True, "positive"),
    ("Robinhood reports July 2026 operating data", True, "neutral"),
    # An acquisition is not inherently good news for the acquirer, so the
    # honest direction here is neutral rather than positive.
    ("Amazon to acquire logistics startup for $1.2 billion", True, "neutral"),
    ("Marvell CFO steps down after four years", True, "negative"),
    # noise that must never reach the page
    ("3 Reasons Nvidia Stock Could Double by 2027", False, None),
    ("Analyst raises Palantir price target to $250", False, None),
    ("Should You Buy Tesla Stock Before Earnings?", False, None),
    ("Better Buy: Microsoft vs. Alphabet", False, None),
    ("Prediction: Amazon Will Be Worth $5 Trillion", False, None),
    ("If You'd Invested $1,000 in Meta in 2015", False, None),
    # thin, non-material coverage
    ("Nvidia CEO spotted at a restaurant in Taipei", False, None),
]


def selftest():
    bad = 0
    for title, want, direction in FIXTURES:
        s, cats, got = score(title)
        published = s >= MIN_SCORE
        ok = published == want and (direction is None or got == direction)
        if not ok:
            bad += 1
        print(f"  {'ok  ' if ok else 'FAIL'} score={s:2d} {got:8} "
              f"{','.join(cats) or '-':22} {title[:56]}")
    print(f"selftest: {len(FIXTURES) - bad}/{len(FIXTURES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
