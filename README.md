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
editions/YYYY-MM-DD.json   one file per day, the source of truth
about.json                 the About block at the foot of the page
research.py                rebuilds the Earnings study from live market data
research/                  its cache: one row per session, plus the calendars
research.json              generated; everything the Earnings section reads
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

`build.py` refreshes `research.json` first whenever it is not from today,
by running `research.py` itself. Pass `--no-research` to skip that and
render whatever is already on file.

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

## Chart buttons

Every ticker name carries a small Chart button, in the day's entries and in
the by-ticker index. It links to finviz's daily-candle chart image for that
symbol. The image is finviz's, fetched by the reader's browser on their
site, not embedded here, so the page itself still loads no third-party
resources and the CSP stays strict. `charts.py` writes two files per ticker into `charts/`: an interactive
full-viewport page (`AAPL.html`) and a static SVG (`AAPL.svg`) used as the
no-script fallback. The interactive page draws to a canvas with a crosshair,
an OHLC and volume readout, a volume panel, price gridlines whose density
follows the window height, and wheel zoom over the time axis. Raw bars are
cached in `charts/data/` so pages can be redrawn without spending API calls.
Both are styled like the site, and `build.py` links a ticker to its
local SVG whenever one exists. Run it with `--demo` to check the renderer
against synthetic data; `index.json` records `demo: true` for those runs
and build.py refuses to link them, because a made-up price chart is
indistinguishable from a real one to a reader.

## Candle intervals

The chart's top bar offers 1m, 3m, 5m, 15m, 30m, 1h and 1D, but only shows
a button for an interval that actually has data, so a run without an
intraday provider yields a chart with just `1D` rather than dead controls.

Intraday needs a provider that serves it on a free tier. Alpha Vantage does
not: `TIME_SERIES_INTRADAY` answers "This is a premium endpoint". Twelve
Data does, and `_from_twelvedata` is wired for it: allow
`api.twelvedata.com` in the environment's network policy and set
`TWELVEDATA_KEY`. No provider offers a 3-minute interval, so `3m` is built
here by rolling up 1-minute bars, open first, close last, high and low the
extremes, volume summed.

Sources are tried in order: Alpha Vantage first when `ALPHAVANTAGE_KEY`
is set in the environment, then stooq. Both are optional and every failure
is silent, so charts.py degrades to drawing nothing rather than erroring.

To turn the local charts on, allow `www.alphavantage.co` in the cloud
environment's network policy and set `ALPHAVANTAGE_KEY` in its
environment variables. Calls are spaced 13 seconds apart to stay inside
the free tier's five-per-minute limit; twelve tickers take about
two and a half minutes.

stooq is allowlisted but serves datacenter traffic a JavaScript
proof-of-work challenge that re-issues on every request, solved or not, so
it yields nothing in practice. It is kept as a fallback in case that
changes.

## Tabs

The page is four things, so it is four panels behind a tab strip: **Brief**
(today, plus the archive of previous days), **Earnings**, **By ticker**, and
**About**. `render_tabs` only offers a tab when there is something behind it,
so a repository with one edition and no `research.json` does not grow dead
links.

The tabs are plain fragment links and the hash is the state, so
`.../#earnings` opens the Earnings panel, the back button steps between
panels, and a link to an anchor inside a panel opens that panel first. Without
JavaScript nothing is hidden: the page is one long document and the tabs jump
to the sections, exactly as it behaved before they existed.

## The Earnings section

`research.py` regenerates `research.json`, which is the only thing the
Earnings section of the page reads. Nothing in that section is typed in by
hand: the figures, the stocks named in the prose, the significance verdicts
and the counts in the sources block are all derived at render time. Editing
the wording to say something the tables do not is how the two start
contradicting each other.

```bash
python3 research.py            # top up the cache, recompute, rewrite research.json
python3 research.py --offline  # recompute from the cache only, no network
python3 research.py --backfill # refetch every ticker's history from 2020
```

The expensive part is price history: thirty-minute bars back to 2020,
reduced to the three prices per session the study actually reads and kept
in `research/sessions/`. A daily run tops up the tail of that with one
request per ticker instead of refetching six years. Earnings calendars in
`research/earnings/` are refreshed only when a report is actually due,
which keeps the AlphaVantage allowance free for `charts.py`. Upcoming dates
come from the published calendar where a company has confirmed one and are
projected from the year-ago quarter where it has not, and the page labels
which is which.

Both keys are optional. Without them the study recomputes from the cache in
the repository, and a provider outage leaves the previous `research.json`
standing rather than publishing a half-finished rebuild.

## House style

`build.py` strips every em dash from the rendered page at build time and puts
a comma in its place, because editions are drafted by a language model and
em dashes are its most obvious tic. Clause-joining dashes need a colon or a
full stop rather than a comma, so those are fixed in the edition JSON itself;
the build-time rule is the safety net, not the first line of defence. En
dashes in numeric ranges are left alone, since those are simply correct.

## Editing the About block

`about.json` holds the name, role, monogram, paragraphs and links shown at
the foot of the page. Change it and rebuild; no Python involved. Delete the
file and the section disappears.

## Publishing

Pushing to `main` is the only publishing step. GitHub Pages serves
`index.html`, which `build.py` regenerates from every edition on file.
