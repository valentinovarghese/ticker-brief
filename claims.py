"""Check the brief's comparative claims against the day's own numbers.

A superlative is the one kind of sentence a reader cannot check and cannot
sanity-check either. "GOOGL fell 4.03%" is either right or visibly wrong,
but "the largest fall of the twelve" is a claim about eleven other stocks
the sentence never names. It is easy to write from a general sense of the
day and easy to get wrong, and nothing downstream catches it.

So every edition carries a `data` block: the per-ticker figures actually
fetched that morning. This module recomputes the rankings from it and
holds the prose to them.

Anything it cannot map to a metric is reported as unverified rather than
passed over. A claim nobody checked should look different from a claim
that was checked and held.
"""

import re

TICKERS = ("AAPL", "AMZN", "TSLA", "PLTR", "MSFT", "GOOGL",
           "HOOD", "NVDA", "INTC", "NBIS", "MRVL", "META")

# Prose names a company as often as it names a ticker, and a subject the
# matcher cannot resolve becomes an unchecked claim rather than a caught
# one. That is exactly how "Tesla has the largest gap" slipped through.
NAMES = {
    "apple": "AAPL", "amazon": "AMZN", "tesla": "TSLA",
    "palantir": "PLTR", "microsoft": "MSFT", "alphabet": "GOOGL",
    "google": "GOOGL", "robinhood": "HOOD", "nvidia": "NVDA",
    "intel": "INTC", "nebius": "NBIS", "marvell": "MRVL", "meta": "META",
}

# How far down the order a hedged superlative may still sit. Three of
# twelve is a leading quarter, which is about what "among the widest"
# promises a reader.
HEDGE_BAND = 3

NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
           "twelve": 12}

# Which end of the ordering each word points at. +1 means "the biggest
# value wins", -1 means "the smallest". The metric itself is chosen
# separately, because "largest fall" and "largest gain" are the same word
# over the same column pointing opposite ways.
EXTREME = {
    "largest": +1, "biggest": +1, "widest": +1, "heaviest": +1,
    "greatest": +1, "worst": +1, "most": +1,
    "smallest": -1, "narrowest": -1, "lightest": -1, "least": -1,
    "best": +1, "strongest": +1, "weakest": -1,
}

# Metric keywords, checked longest-phrase-first so "below its 52-week high"
# beats a bare "high". Each maps to a column in the snapshot and a sign
# that turns the raw number into "more of the thing being claimed".
METRICS = (
    ("52-week high", "gap", -1),
    ("its high", "gap", -1),
    ("gap", "gap", -1),
    ("discount", "gap", -1),
    ("premarket", "premarket_pct", +1),
    ("participation", "volratio", +1),
    ("volume", "volratio", +1),
    ("fall", "pct", -1),
    ("decline", "pct", -1),
    ("drop", "pct", -1),
    ("loss", "pct", -1),
    ("gain", "pct", +1),
    ("rise", "pct", +1),
    ("move", "pct", +1),
)


def columns(data):
    """Per-ticker metric values, derived once from the stored snapshot."""
    out = {}
    for t, v in data.get("tickers", {}).items():
        pre = v.get("premarket_pct")
        out[t] = {
            "pct": v["pct"],
            "gap": v["close"] / v["high_52w"] * 100 - 100,
            "volratio": v["volume"] / v["avg_volume"] * 100 - 100,
            "premarket_pct": pre,
        }
    return out


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s).replace("&middot;", ",") \
                                    .replace("&amp;", "&").replace("&ndash;", "-")


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", strip_tags(text))
            if s.strip()]


def walk_strings(node, path="", owner=None):
    """Yield (path, text, owner). `owner` is the ticker whose block the text
    sits in, because an entry's own prose usually refers to it as "it" and
    names only the yardstick: "the smallest gap on this list after Amazon"
    is a claim about Nvidia, in Nvidia's block, that never says Nvidia."""
    if isinstance(node, dict):
        owner = node.get("ticker") if node.get("ticker") in TICKERS else owner
        for k, v in node.items():
            if k == "data":
                continue                    # the snapshot is not prose
            yield from walk_strings(v, f"{path}/{k}", owner)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk_strings(v, f"{path}[{i}]", owner)
    elif isinstance(node, str):
        yield path, node, owner


def yardsticks(sentence):
    """Tickers named as the thing being measured against, not the subject.

    Scans the few words after "after"/"behind" rather than a fixed slot: in
    "behind Tesla at -42.3%" an optional-word pattern eats the name and
    returns "at", which silently turns the yardstick into the subject.
    """
    found = []
    for m in re.finditer(r"(?:after|behind)\s+((?:\w+[\s,]+){0,2}\w+)",
                         sentence):
        for word in re.split(r"[\s,]+", m.group(1)):
            tick = NAMES.get(word.lower()) or (word.upper()
                                               if word.upper() in TICKERS
                                               else None)
            if tick and tick not in found:
                found.append(tick)
    return found


def pick_metric(sentence):
    low = sentence.lower()
    best = None
    for phrase, col, sign in METRICS:
        i = low.find(phrase)
        if i >= 0 and (best is None or len(phrase) > len(best[0])):
            best = (phrase, col, sign)
    return best


def rank_of(ticker, col, sign, cols):
    """1-based rank of `ticker` when sorted by "most of the thing"."""
    have = {t: c[col] for t, c in cols.items() if c.get(col) is not None}
    if ticker not in have:
        return None, None
    order = sorted(have, key=lambda t: have[t] * sign, reverse=True)
    return order.index(ticker) + 1, order


def check_rank_claims(cols, path, sentence, errors, unverified, owner=None):
    low = sentence.lower()
    words = [w for w in EXTREME if re.search(rf"\b{w}\b", low)]
    if not words:
        return False
    subjects = [t for t in TICKERS if re.search(rf"\b{t}\b", sentence)]
    for name, tick in NAMES.items():
        if re.search(rf"\b{name}\b", low) and tick not in subjects:
            subjects.append(tick)
    # A name inside an "after X" exclusion is the yardstick, not the subject.
    # Drop it even when it is the only name present: the subject is then the
    # block's own ticker, which the sentence left implicit.
    marks = yardsticks(sentence)
    for tick in marks:
        if tick in subjects:
            subjects.remove(tick)
    if not subjects and owner:
        subjects = [owner]
    metric = pick_metric(sentence)
    if not metric or len(subjects) != 1:
        unverified.append((path, sentence))
        return True

    phrase, col, msign = metric
    word = words[0]
    sign = msign * (1 if EXTREME[word] > 0 else -1)
    subject = subjects[0]

    # A hedge ("among the widest", "one of the lightest") claims membership
    # of a small leading group, not the top place. It is honest language and
    # the prose is worse without it, so allow a band rather than a rank. The
    # band is still a claim: "among the widest" of rank 9 is a lie.
    hedged = re.search(r"\b(among the|one of the|some of the)\b", low)

    # "second-largest", "after X" and "behind X" all shift the expected
    # rank down by the names excluded, so read the offset off the sentence.
    expected = 1
    if re.search(r"\bsecond[- ]", low):
        expected = 2
    elif re.search(r"\bthird[- ]", low):
        expected = 3
    if marks:
        expected = max(expected, len(marks) + 1)

    got, order = rank_of(subject, col, sign, cols)
    if got is None:
        unverified.append((path, sentence))
        return True
    if hedged:
        if got > HEDGE_BAND:
            errors.append(
                f"{path}: hedges {subject} as {word} on {col}, but it ranks "
                f"{got} of {len(order)}, outside the top {HEDGE_BAND}. "
                f"Order: {', '.join(order[:4])}...\n    {sentence}")
    elif got != expected:
        errors.append(
            f"{path}: claims {subject} is rank {expected} on {col} "
            f"(\"{word}\"), but it is rank {got}. "
            f"Order: {', '.join(order[:4])}...\n    {sentence}")
    return True


def check_count_claims(cols, path, sentence, errors, unverified):
    """Verify "N of the twelve ..." against the condition it names."""
    # Only a number in front of "of the twelve" makes this a count claim.
    # Matching any word swallowed "the largest fall of the twelve" and other
    # rank claims, parking them as unverifiable when they were checkable.
    m = re.search(r"\b(" + "|".join(NUMBERS) + r"|\d+) of the twelve\b",
                  sentence, re.I)
    if not m:
        return False
    raw = m.group(1).lower()
    n = NUMBERS.get(raw, int(raw) if raw.isdigit() else None)

    low = sentence.lower()
    if "below-average volume" in low or "below average volume" in low:
        actual = sum(1 for c in cols.values() if c["volratio"] < 0)
    elif "above" in low and ("average" in low or "averages" in low):
        actual = sum(1 for c in cols.values() if c["volratio"] > 0)
    else:
        unverified.append((path, sentence))
        return True

    if n != actual:
        errors.append(f"{path}: says {n} of the twelve, the data says "
                      f"{actual}.\n    {sentence}")
    return True


def verify(edition):
    """Return (errors, unverified) for one edition dict."""
    data = edition.get("data")
    if not data:
        return ([], [("", "no `data` snapshot: comparative claims in this "
                          "edition cannot be checked at all")])
    cols = columns(data)
    errors, unverified = [], []
    for path, text, owner in walk_strings(edition):
        for sentence in sentences(text):
            if check_count_claims(cols, path, sentence, errors, unverified):
                continue
            check_rank_claims(cols, path, sentence, errors, unverified, owner)
    return errors, unverified
