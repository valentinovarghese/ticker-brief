# Ticker Brief

A daily pre-market brief on twelve tickers — AAPL, AMZN, TSLA, PLTR, MSFT,
GOOGL, HOOD, NVDA, INTC, NBIS, MRVL, META — written to explain why each
number changes what a company is worth, not just to list the numbers.

Written by a scheduled Claude Code routine each weekday. The brief is
delivered by push notification and email; this repository is the permanent
archive behind it.

**Read it here:** <https://valentinovarghese.github.io/ticker-brief/>

## How it works

```
editions/YYYY-MM-DD.json   one file per day — the source of truth
build.py                   renders every edition into site.html
index.html                 generated; served by GitHub Pages from main
site.html                  generated; identical copy of index.html
```

Each weekday the routine researches the day, writes one new JSON file,
rebuilds the page from **all** editions on file, and pushes the commit.
Pushing to `main` is what publishes — GitHub Pages rebuilds a minute or two
later, so the page lags the email slightly.

Because the page is regenerated from the repository rather than read back
out of itself, history is lossless and unbounded. Delete a JSON file and it
disappears from the site; restore it and it comes back.

Once there are at least two editions on file, the page also grows a **By
ticker** section: one row per ticker, one chip per day it appeared, coloured
by direction and carrying that day's move. It is the fastest way to see how
a single name has been treated over time without opening each day.

## Running it yourself

No dependencies — Python 3 standard library only.

```bash
python3 build.py --check   # validate every edition, write nothing
python3 build.py           # write site.html
open site.html             # or: python3 -m http.server
```

`--check` fails loudly on malformed JSON or a missing required key
(`date`, `headline`, `quick`, `entries`), so a bad edition never reaches
the published page.

## Reading the briefs offline

Every edition is plain JSON, so the archive is greppable:

```bash
grep -l MSFT editions/*.json          # every day Microsoft appeared
jq -r '.headline' editions/*.json     # every headline, oldest first
```

## Conventions

- **Direction** — ▲ bullish, ▼ bearish, ● neutral. Describes what the data
  changes, not what the price will do.
- **Strength** — major (3%+), notable (1–3%), minor (under 1%).
- **Flagged** — an item where the stock has *not* moved in line with the
  data. These are the ones worth a second look.
- Opinion pieces and analyst price targets are excluded by design.

Nothing here is a prediction or investment advice.
