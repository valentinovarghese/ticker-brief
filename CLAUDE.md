# Working rules for this repository

Read this before writing an edition.

## The rule that matters most

**Never write a comparative claim from memory. Query it.**

"Largest", "smallest", "only", "widest", "lightest", "best", "worst",
"second-", "N of the twelve": every one of these is a statement about all
twelve tickers, and it is the one kind of sentence a reader cannot check.
A number is either right or visibly wrong. A ranking sounds equally
confident either way.

This has failed in practice. On 2026-08-06 two claims went out wrong:
"the largest gap to its high after Robinhood" for a stock that ranked
third, and "ten of the twelve" when the answer was nine. Both were written
from a general sense of the day, minutes after the correct data had been
fetched and was sitting in the session.

So: before writing any such phrase, run the comparison over the day's
data and read the answer off the output. Not from recollection of the
table, from the output.

## Every edition carries its evidence

Each edition JSON has a `data` block: per-ticker `close`, `pct`, `open`,
`high`, `low`, `volume`, `avg_volume`, `high_52w`, `premarket_pct`,
`afterhours_pct`, plus the session date and the source. It is the
morning's fetch, preserved.

The last two are the same feed at different hours and only one of them is
ever populated. Twelve Data's `extended_*` fields carry whichever extended
session is current, so read the `extended_timestamp` before deciding which
column the number belongs in. On 2026-08-28 the feed served 19:59 ET the
previous evening for all twelve tickers, so there was no premarket read at
all that morning. Record the null rather than filing an evening print as a
premarket one.

Populate it from the same fetch used to write the prose. Never hand-type
it, and never copy figures from press coverage into it: the point of the
block is that it is the primary record the prose is held against.

## The checker

`claims.py` recomputes rankings from that block and holds the prose to
them. It runs inside `build.py --check`, which the routine runs before it
publishes, so a contradicted claim cannot reach the page.

    python3 build.py --check    # fails on any contradicted claim

Three outcomes:

- **CLAIM FAILED** — the data contradicts the sentence. Fix the prose, or
  fix the snapshot if the snapshot is what is wrong. Never delete the
  claim to silence the check without establishing which one was right.
- **could not map to a metric** — listed, not failed. These are claims
  nobody has checked. Read every one and confirm it by hand. A claim that
  was never checked should not look like a claim that passed.
- silence — checked and held.

Hedges ("among the widest", "one of the lightest") are allowed and are
still bounded: the subject must rank in the top three, or the check fails.

## Charts

`charts.py` falls back to cached bars when a fetch is refused, which is
the right behaviour and also an invisible failure: a chart missing
yesterday reads as a flat day, not as an error. It now reports which
daily series are behind the others and exits non-zero when any are.

The routine runs it as `charts.py || true`. Keep it that way. A stale
chart must be loud but must never withhold the brief. **Watch the run log
for `charts: STALE`.** If it appears, say so in the brief rather than
publishing a chart that quietly omits a session.

## Data sources

- **Twelve Data** (`TWELVEDATA_KEY`) is the working source for quotes,
  intraday and daily. Free tier is 8 credits/min; a batch quote costs one
  credit per symbol, so chunk requests and space them.
- **Alpha Vantage** (`ALPHAVANTAGE_KEY`) allows 25 calls a day. Twelve
  tickers exhaust it in a couple of runs, after which it answers HTTP 200
  with an `Information` notice instead of a series. Treat a missing series
  as throttling, not as an outage.
- **stooq** is allowlisted but serves datacenter traffic a challenge page.
- **sec.gov and Yahoo Finance are blocked by the environment proxy**
  (403 on the CONNECT tunnel). Do not plan around either. If a filing
  matters, say the filing could not be read directly and attribute the
  detail to the coverage.

## Editorial depth and Market reports

The site should read as a small, useful market publication. The daily
`market/YYYY-MM-DD.json` report appears near the top under Market. It
covers General market (equities, Treasuries and bonds, credit, currencies,
crypto, commodities, housing and US policy) and Wider market (UK, euro area, China,
Japan and other consequential regions). Publish one report every calendar
day. Give each item a specific dated fact, enough detail to understand it,
the mechanism by which it matters, a concrete next test and a direct source.
Carry forward older policy or data only with its true observation date
visible. Research current primary releases and reputable reporting afresh
each day. Never invent a price move, policy decision, or release to fill a
category. `market_gate.py` checks structure and minimum depth; the author
must still check each fact against its source.

The twelve-ticker edition should match the depth of the early editions and
the user's long-form reference. For each ticker explain what happened,
why it changes or does not change the investment case, at least two
developed analytical points, what may already be priced in, what evidence
would change the view, and the next dated catalyst or explicit unscheduled
watch. Include concrete price and volume figures and visible source links.
Separate measured market action from inference about its cause. A quiet
company day deserves an honest, useful no-event analysis, not fabricated
news or boilerplate. The new fields `analysis`, `priced_in`,
`would_change` and `next_date` render in `build.py` and are required
by `edition_gate.py` for new stock editions.

## Dating and publication

The Market report runs every calendar day at 22:00 Europe/London. The
stock edition runs only on eligible trading weekdays after 17:00 ET. Its date
and the session it reports are the same completed trading day. Check the
clock and the NYSE holiday calendar before drafting. Run
`session_snapshot.py` to fetch Twelve Data `1day` bars, and copy that
snapshot's `tickers` block unchanged into the edition. The `/quote`
endpoint has repeatedly returned a 09:30 ET timestamp after the close;
do not use it as close evidence.

The Codex post-close automation is the sole scheduled publisher.
The GitHub `daily-brief.yml` workflow is a manual source check. Before
publishing, run `market_gate.py` and, when applicable, `edition_gate.py`
against the saved snapshot, then
`build.py --check`, then `build.py`. Preserve all prior editions and do not
publish a price-only placeholder. See `PUBLICATION.md` for the full runbook.

Date every item before writing it up. A fresh article about an old event
is an old event, and this list attracts them: recycled coverage of the
Nvidia/OpenAI backstop, Berkshire's exit from Amazon and the Bezos Form
144 all surfaced as though they were new. Name the date, or leave it out.
