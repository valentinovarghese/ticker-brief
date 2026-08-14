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

# SEC's fair-access policy requires a User-Agent naming the requester with a
# working contact, and answers a generic one with 403. The address is the
# owner's GitHub noreply, which is already public, rather than a personal
# mailbox published in a public repository.
UA = ("ticker-brief/1.0 "
      "(valentinovarghese@users.noreply.github.com) "
      "+https://github.com/valentinovarghese/ticker-brief")

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

# Every noun here carries an explicit optional plural. "contract" without it
# does not match "Contracts", which silently dropped a real Space Force
# contract award on the first live run. A missing plural loses news without
# leaving a trace, so the plurals are spelled out rather than assumed.
CATEGORIES = [
    # "reports"/"operating data" matter: Robinhood's monthly metrics release
    # is exactly the kind of scheduled, numeric disclosure this feed is for.
    ("earnings",   6, r"\b(earnings|results?|revenues?|eps|guidance|forecasts?|"
                      r"outlooks?|quarterly|q[1-4]\s*(?:20\d\d|fy)|beats?|"
                      r"misses?|reports?|reported|operating data|"
                      r"monthly metrics|deliveries|shipments|"
                      r"pre-?announces?)\b"),
    ("filing",     6, r"\b(8-ks?|10-ks?|10-qs?|13-?[dgf]|form [345]|s-1|6-k|"
                      r"proxy|proxies|prospectus(?:es)?|sec filings?|"
                      r"files? with the sec)\b"),
    ("legal",      5, r"\b(lawsuits?|sues?|sued|settle(?:s|d|ment|ments)?|"
                      r"antitrust|doj|ftc|sec (?:probe|investigat|charge)|"
                      r"subpoenas?|injunctions?|contempt|appeals?|courts?|"
                      r"judges?|rulings?|fine[ds]?|penalties|penalty|"
                      r"regulators?|investigations?|probes?)\b"),
    ("capital",    5, r"\b(buybacks?|repurchases?|dividends?|offerings?|"
                      r"issuances?|notes|debt|convertibles?|stakes?|"
                      r"spin-?offs?|splits?)\b"),
    ("ma",         5, r"\b(acquir\w+|acquisitions?|mergers?|takeovers?|buys?|"
                      r"divest\w*|sells? (?:its|unit|division))\b"),
    ("contract",   5, r"\b(contracts?|deals?|agreements?|award(?:ed|s)?|"
                      r"orders?|partnerships?|supply|wins?|won)\b"),
    ("operations", 5, r"\b(recalls?|recalled|halts?|halted|outages?|breach(?:es)?|"
                      r"hacks?|layoffs?|cuts? \d+|shutdowns?|delays?|delayed|"
                      r"plants?|factory|factories|fabs?|production)\b"),
    # A job title alone is not news. Only an actual change of who holds it is,
    # which is why "Nvidia CEO spotted in Taipei" must not score here.
    ("leadership", 5, r"\b(resign\w*|steps? down|stepping down|departs?|"
                      r"departures?|ousted|fired|appoints?|appointed|"
                      r"succeeds?|named (?:ceo|cfo|chair))\b"),
    ("policy",     4, r"\b(tariffs?|sanctions?|export (?:ban|control|licen)|"
                      r"bans?|banned|approvals?|approves?|antitrust|"
                      r"national security)\b"),
]

# Coverage that is opinion, promotion or ranking. Excluded by design, the
# same way the brief excludes it.
NOISE = re.compile(
    r"(price target|should you buy|is it too late|best stocks?|top \d+ stocks?|"
    r"\b\d+ (?:reasons?|things|stocks?)\b|motley fool|zacks|prediction|"
    r"here'?s why you|could (?:double|soar|explode)|millionaire|"
    r"better buy|vs\.?\s|analyst[s]? say|rated? (?:buy|sell|hold)|"
    r"my top|i'?m buying|dividend king|if you'?d invested|stock split soon|"
    # Promotional and message-board register.
    r"must buy|huge upside|is a buy|\bbuy right now|after the crash|"
    r"time to buy|worth buying|screaming buy|\bbuy the dip|"
    # Retrospective explainers and previews, not events.
    r"stock market forecast|earnings preview|week ahead|what to expect|"
    r"stocks? to (?:buy|watch)|ahead of earnings|things to know|"
    r"here'?s what|why .{0,30}\bstock (?:slid|soared|rose|fell|jumped|"
    r"dropped|climbed|sank|is (?:up|down|moving|rising|falling))|"
    r"what'?s (?:going on|driving)|moved? (?:up|down) by \d|"
    r"\bopinions?\b|analyst (?:downgrade|upgrade|rating)|"
    # Auto-generated 13F ownership stubs. Every large holder files one every
    # quarter, so these arrive by the hundred and say nothing about the
    # company itself.
    r"shares (?:acquired|sold|purchased) by|has \$[\d.,]+ (?:million|billion) "
    r"(?:stake|position)|(?:buys|sells|acquires|purchases) "
    r"(?:new )?(?:\d[\d,]* )?shares of|position (?:raised|lowered|boosted|"
    r"trimmed|increased|decreased) by|(?:stake|holdings|position) in .{0,40} "
    r"(?:raised|lowered|boosted|trimmed)|takes? position in|"
    r"reports \d+% ownership|invests \$[\d.,]+ (?:million|billion) in)",
    re.I)

# Outlets that publish only ranking pieces, promotional copy or
# machine-written ownership stubs. Blocking the source is blunt, but these
# produce nothing this feed is for and they crowd out everything else.
SOURCE_BLOCK = {
    "marketbeat", "mshale.com", "zacks", "the motley fool", "fool.com",
    "tipranks", "24/7 wall st.", "247wallst", "pluang", "insider monkey",
    "stocktwits", "benzinga", "simply wall st", "gurufocus",
}

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

# A headline naming three or more of the twelve is a round-up, not a story
# about any one of them.
MAX_TICKERS = 2


def about(ticker, title):
    """Is this headline actually about this company?

    Google's query matches loosely, and short names are the trap. "Hood
    River Capital exits Camping World" matched HOOD and has nothing to do
    with Robinhood. So the ticker must appear in capitals as a whole word,
    or the full company name must appear as a phrase. "Hood" alone is
    neither, which is exactly the point.
    """
    if re.search(r"(?<![A-Za-z])" + re.escape(ticker) + r"(?![A-Za-z])", title):
        return True
    return re.search(r"\b" + re.escape(NAMES[ticker]) + r"\b", title, re.I) is not None


def round_up(title):
    """Does the headline name enough tickers to be a list rather than a story?"""
    hits = sum(1 for t in TICKERS
               if re.search(r"(?<![A-Za-z])" + t + r"(?![A-Za-z])", title))
    return hits >= MAX_TICKERS + 1


def blocked_source(source):
    s = (source or "").lower()
    return any(b in s for b in SOURCE_BLOCK)


def signature(title):
    """The significant words of a headline, for near-duplicate detection."""
    words = re.findall(r"[a-z0-9$%.]+", title.lower())
    return {w for w in words if len(w) > 3}


def near_duplicate(sig, seen_sigs, threshold=0.45):
    """Wire copy repeats. One Berkshire headline is news, four is a pile.

    Containment rather than Jaccard: four outlets rewriting one story share
    the entities and little else, so overlap against the *shorter* headline
    is the signal. Jaccard scored that cluster at 0.25 and collapsed none of
    it. The trade is that two genuinely different stories sharing most of
    their short headline can merge; capping items per ticker and exempting
    filings keeps that cost small.
    """
    for other in seen_sigs:
        smaller = min(len(sig), len(other))
        if smaller and len(sig & other) / smaller >= threshold:
            return True
    return False


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


# What each form actually tells a reader, so the page says something more
# useful than a form number.
FORMS = {
    "8-K": "current report, a disclosable event",
    "10-Q": "quarterly report",
    "10-K": "annual report",
    "4": "insider share transaction",
    "3": "initial insider holding",
    "5": "annual insider holding",
    "SC 13D": "activist stake, over 5%",
    "SC 13G": "passive stake, over 5%",
    "13F-HR": "quarterly institutional holdings",
    "S-1": "registration of new securities",
    "S-3": "shelf registration",
    "S-8": "employee share plan",
    "424B5": "prospectus for a securities offering",
    "6-K": "foreign issuer report",
    "20-F": "foreign issuer annual report",
    "DEF 14A": "proxy statement",
}

# Routine plumbing that would bury the material filings.
FORM_NOISE = {"S-8", "3", "5", "SD", "ARS", "CERT", "8-A12B", "25-NSE", "144"}


def sec_filings(ticker):
    """Recent filings from EDGAR's submissions API, newest first.

    Uses data.sec.gov rather than the old browse-edgar Atom feed: it is the
    documented, stable interface and returns clean JSON instead of titles
    that have to be split apart.
    """
    cik = CIK.get(ticker)
    if not cik:
        return []
    data = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accs = recent.get("accessionNumber") or []
    docs = recent.get("primaryDocument") or []

    out = []
    for i, form in enumerate(forms[:40]):
        if form in FORM_NOISE:
            continue
        when = parse_dt(dates[i]) if i < len(dates) else None
        acc = accs[i].replace("-", "") if i < len(accs) else ""
        doc = docs[i] if i < len(docs) else ""
        link = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
                if acc and doc else
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                f"&CIK={cik}&type={urllib.parse.quote(form)}")
        gloss = FORMS.get(form)
        out.append({"title": f"Form {form} filed" + (f": {gloss}" if gloss else ""),
                    "detail": form,
                    "link": link,
                    "published": when,
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
            # A filing is material by construction, whatever its title says,
            # and it comes from EDGAR so none of the coverage filters apply.
            if rec["primary"]:
                s = max(s, MIN_SCORE + 3)
                if "filing" not in cats:
                    cats.append("filing")
            else:
                if s < MIN_SCORE:
                    continue
                if blocked_source(rec["source"]):
                    continue
                # Must be about this company, and about this company alone.
                if not about(ticker, rec["title"]):
                    continue
                if round_up(rec["title"]):
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

    # Highest-scoring first, so when a cluster of wire copy collapses it is
    # the most material phrasing that survives.
    seen, sigs, unique = set(), [], []
    for it in sorted(items, key=lambda i: (-i["score"], i["published"] or "")):
        if it["id"] in seen:
            continue
        sig = signature(it["title"])
        # Filings are never collapsed: two 8-Ks on one day are two events.
        if not it["primary"] and near_duplicate(sig, sigs):
            continue
        seen.add(it["id"])
        sigs.append(sig)
        unique.append(it)

    unique.sort(key=lambda i: (i["published"] or "", i["score"]), reverse=True)
    return unique[:KEEP_PER_TICKER], errors


# How long the file may go untouched before a run rewrites it purely to
# prove the job is alive. Without this the file would only change when the
# news changed, and a quiet overnight stretch would be indistinguishable
# from a workflow that had stopped running.
HEARTBEAT = timedelta(minutes=55)


def previous():
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    now = datetime.now(timezone.utc)
    dry = "--dry-run" in sys.argv

    payload = {"checked": now.isoformat(timespec="seconds"),
               "changed": now.isoformat(timespec="seconds"),
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

    # Every source failing usually means egress is blocked, not that the news
    # stopped. Never overwrite a good file with an empty one on a bad run.
    old = previous()
    if failed == len(TICKERS) and old.get("tickers"):
        print("news: NO SOURCE REACHABLE for any ticker, "
              "keeping the previous file")
        emit_changed(False)
        return 1

    # The run happens every five minutes; the news does not. Rewriting the
    # file each time would commit ~288 times a day and bury the archive's
    # real history. So the file is only rewritten when the items actually
    # differ, plus an hourly heartbeat that proves the job is still alive.
    same = old.get("tickers") == payload["tickers"]
    last = parse_dt(old.get("checked") or "") if old else None
    due = last is None or (now - last) >= HEARTBEAT

    if same and not due:
        print("news: unchanged, nothing to commit")
        emit_changed(False)
        return 0

    # A heartbeat must not claim the content changed when it did not.
    if same:
        payload["changed"] = old.get("changed") or payload["changed"]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}"
          + (" (heartbeat, items unchanged)" if same else " (items changed)"))
    emit_changed(True)

    if failed == len(TICKERS):
        print("news: NO SOURCE REACHABLE for any ticker")
        return 1
    return 0


def emit_changed(changed):
    """Tell the workflow whether there is anything worth committing."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")


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


# Real headlines the first live run let through that it should not have,
# plus the ones it correctly kept. Every one of these came off the wire on
# 2026-08-14, so this is a regression test against observed behaviour rather
# than against imagined behaviour.
LIVE_FIXTURES = [
    # (ticker, headline, source, should_publish)
    ("HOOD", "Why HOOD Stock Is A MUST BUY Right Now (Huge Upside)", "mshale.com", False),
    ("HOOD", "HOOD Stock Plunges 6.15%! Is Robinhood A Buy After The Crash?", "mshale.com", False),
    ("HOOD", "Hood River Capital exits Camping World (CWH) with reported 0% ownership", "Stock Titan", False),
    ("MSFT", "Sunbelt Securities Inc. Has $29.07 Million Stake in Microsoft Corporation", "MarketBeat", False),
    ("MSFT", "Guardian Partners Inc. Buys 2,824 Shares of Microsoft Corporation $MSFT", "MarketBeat", False),
    ("NVDA", "NVDA, MRVL, AVGO - 3 Semiconductor Stocks to Buy Ahead of Earnings", "TipRanks", False),
    ("NVDA", "5 AI Stocks with Strong Growth to Buy on the Rebound", "Benzinga", False),
    ("META", "Stock Market Forecast | BTC TSLA NVDA AAPL AMZN META MSFT", "mshale.com", False),
    ("META", "Why Meta Stock Slid After Earnings While Microsoft Soared", "AOL.com", False),
    ("MRVL", "Marvell or Nvidia: Which AI Chip Stock Does Goldman Sachs Prefer", "TipRanks", False),
    ("AAPL", "Apple Stock (AAPL) Opinions on Recent Earnings and Analyst Downgrades", "quiverquant.com", False),
    # These are real events and must survive.
    ("GOOGL", "Berkshire Adds to Alphabet Stake, Buys Homebuilders", "WSJ", True),
    ("AMZN", "Joshua Kushner's Thrive Capital discloses $215 million Amazon stake", "Reuters", True),
    ("INTC", "Intel Corp (INTC) CEO Tan Lip Bu acquires 105,263 shares in Family Trust", "Stock Titan", True),
    ("AMZN", "Rocket Lab, Amazon Win Space Force Contracts", "Investor's Business Daily", True),
    ("NVDA", "Nvidia discloses big stake in SpaceX in Q2 moves", "Seeking Alpha", True),
]


def publishable(ticker, title, source):
    """The full coverage gate, exactly as collect() applies it."""
    s, _, _ = score(title)
    return (s >= MIN_SCORE
            and not blocked_source(source)
            and about(ticker, title)
            and not round_up(title))


def selftest():
    bad = 0
    print("-- scoring --")
    for title, want, direction in FIXTURES:
        s, cats, got = score(title)
        published = s >= MIN_SCORE
        ok = published == want and (direction is None or got == direction)
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} score={s:2d} {got:8} "
              f"{','.join(cats) or '-':22} {title[:56]}")

    print("-- live wire, observed 2026-08-14 --")
    for ticker, title, source, want in LIVE_FIXTURES:
        got = publishable(ticker, title, source)
        ok = got == want
        bad += not ok
        verdict = "keep" if got else "drop"
        print(f"  {'ok  ' if ok else 'FAIL'} {verdict:5} {ticker:6} {title[:60]}")

    total = len(FIXTURES) + len(LIVE_FIXTURES)
    print(f"selftest: {total - bad}/{total} passed")
    return 1 if bad else 0


def collapse(titles):
    sigs, kept = [], []
    for title in titles:
        sig = signature(title)
        if near_duplicate(sig, sigs):
            continue
        sigs.append(sig)
        kept.append(title)
    return kept


def dedupe_selftest():
    """One story told four ways collapses; two real stories do not."""
    bad = 0

    cluster = ["Berkshire Adds to Alphabet Stake, Buys Homebuilders",
               "Berkshire ups Alphabet stake under Greg Abel, making it a top-3 holding",
               "Berkshire buys more Alphabet, which becomes its third-largest stock",
               "Berkshire boosted Alphabet stake by 83% in biggest buying quarter"]
    kept = collapse(cluster)
    ok = len(kept) == 1
    bad += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} wire cluster: {len(cluster)} -> {len(kept)} "
          f"(want 1)")

    # Negative control: two distinct Intel events must both survive.
    distinct = ["Intel prices $20 billion stock offering at $95 per share",
                "Intel CEO Tan Lip Bu acquires 105,263 shares in Family Trust"]
    kept2 = collapse(distinct)
    ok2 = len(kept2) == 2
    bad += not ok2
    print(f"  {'ok  ' if ok2 else 'FAIL'} distinct events: {len(distinct)} -> "
          f"{len(kept2)} (want 2)")

    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest() or dedupe_selftest())
    sys.exit(main())
