
Search the web for news from the past 24 hours on: AAPL, AMZN, TSLA, PLTR,
MSFT, GOOGL, HOOD, NVDA, INTC, NBIS, MRVL, META.

Only concrete, data-based events: earnings and guidance changes, SEC filings
(8-K, 13-D/G, Form 4), M&A, spin-offs, debt/equity issuance, buybacks,
dividend changes, contracts with dollar values, regulatory or legal actions,
analyst-day hard numbers. Exclude opinion pieces, price targets, commentary.

=== WHEN THIS RUNS ===
This fires at 12:00 UK time — 7am in New York, before the US market opens.
The only price data you have is the previous session's close plus any
after-hours and premarket trading. Always say which one you are using.
Treat a premarket move as provisional: volume is thin and it frequently
reverses at the open. Never write about a premarket move as though it were
a settled reaction, and never imply the market has "decided" anything
before the bell.

=== WHAT THIS BRIEF IS FOR ===
I can find the numbers myself. What I need is why a number changes what a
company is worth. Write for someone who follows markets but has not
memorized the mechanics. Every number must come with what it changes.

=== HOW TO WRITE IT ===
Plain English. No jargon without a gloss the first time it appears — write
"free cash flow (cash left after spending)" or "backlog (revenue already
under contract)". No sentence longer than 25 words. Active voice. Never
write a sentence I would have to re-read.

=== STRUCTURE ===
Line 1, exactly: TICKER BRIEF
Line 2: one standalone sentence naming the day's most important item. This
becomes my phone banner — lead with the ticker and the number.

THE 30-SECOND VERSION — three bullets max. Someone who stops here still has
the day.

MARKET-WIDE — macro from the past 24h (Fed, CPI/jobs, tariffs, geopolitics).
For each, one line on how it actually reaches these stocks: which input it
moves (borrowing costs, consumer spending, input costs, corporate capex) and
why that hits fast-growing tech harder or softer than the market overall.
Use QQQ's move as the gauge. If QQQ contradicts the macro read, say so.

THEN ONE BLOCK PER TICKER:
  TICKER — direction (bullish/bearish/neutral) and strength
           (MAJOR 3%+ / NOTABLE 1-3% / MINOR under 1%)
  What happened: one sentence.
  The numbers: the figure vs. what was expected, and vs. last quarter or
    last year. A number with no comparison is not information.
  Why it matters: 2-3 sentences tracing the chain — this number changes X in
    the business, which changes what the stock is worth because Y. Name what
    it moves: growth rate, margins, cash flow, backlog, or what investors
    will pay per dollar of earnings.
  Already priced in? Compare the news to the previous session's close and to
    any after-hours or premarket move, naming which you used. Moved in line
    → "largely priced in." Hasn't moved or moved opposite → flag it and say
    what the market seems to be weighting instead. If the only evidence is
    premarket, mark the read provisional and say the open will settle it.
  Would flip if: one specific thing that would reverse the read.
  Next date: one concrete upcoming date or trigger.

HARD RULE: "Why it matters" may never restate the event or the numbers. If
it could be written by someone who only read the headline, it is wrong.
  Bad:  "Bullish because earnings beat by 12%."
  Good: "Azure's growth rate is the number investors set Microsoft's price
         on. Speeding up from 40% to 43% raises how long they will assume
         that growth lasts — worth more than the earnings beat itself."

READ-THROUGHS: if one company's news materially affects another ticker on
the list, say so and why. A hyperscaler raising capex is revenue for the
chip and cloud names.

ASYMMETRIES: if two companies did a similar thing and the market treated
them differently, explain the difference. That contrast is usually the most
useful thing in the brief.

SECTOR VS. COMPANY: if a ticker moved big with no company-specific news, say
so plainly and name the real driver. Never let a sector move pose as a
company event.

Sort major → minor. Then "Nothing material: X, Y, Z." and "Earnings coming
up:" with any ticker reporting within 14 days plus the date.

Do not manufacture a read. Routine filings are neutral/minor. A quiet day
should be short. Never present any of this as a prediction. English, under
1000 words. Go deep on the top 3-4 items; one line is enough for minor ones.

=== DELIVERY — follow exactly ===
Call PushNotification with the ENTIRE brief inside <routine_summary> tags.
That text is delivered to my inbox as the email body. Anything outside the
tags never reaches me. Send on every run, including quiet days — on a quiet
day just make it short.

Do NOT create a Gmail draft and do NOT attempt to send email. The Gmail
connector here cannot send, and it points at a mailbox I do not read.

=== THEN: ARCHIVE AND PUBLISH ===
Do this after the notification has been sent. If any step fails, the brief
has already reached me, so report the failure and stop rather than retrying
in a loop.

1. Clone the archive:
     git clone https://github.com/valentinovarghese/ticker-brief.git brief && cd brief
2. Write today's edition to editions/YYYY-MM-DD.json, matching the schema of
   the existing files exactly. Read the most recent edition first and mirror
   its structure. Set "date" to today in YYYY-MM-DD.
3. Build and verify:
     python3 build.py --check && python3 build.py
   If --check fails, fix the JSON before continuing.
4. Publish site.html with the Artifact tool, passing:
     url: https://claude.ai/code/artifact/c669742e-ea78-4d3e-a530-7799e3f0adb1
     favicon: 📈
   Passing that url is required — without it a new page is created and the
   archive is orphaned.
5. Commit and push:
     git add -A
     git commit -m "brief: YYYY-MM-DD"
     git push -u origin main
   Retry a failed push up to 4 times with 2s/4s/8s/16s backoff.

The repository is the archive and the only source of truth. The published
page is regenerated from it each day, so history is never lost and nothing
is ever read back out of the page itself.
