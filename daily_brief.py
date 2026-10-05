#!/usr/bin/env python3
import json, os, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).parent
SYMBOLS=['AAPL','AMZN','TSLA','PLTR','MSFT','GOOGL','HOOD','NVDA','INTC','NBIS','MRVL','META']
HOLIDAYS={'2026-01-01','2026-01-19','2026-02-16','2026-04-03','2026-05-25','2026-06-19','2026-07-03','2026-09-07','2026-11-26','2026-12-25'}
def num(v):
    try:return float(v)
    except (TypeError,ValueError):return None
def quote(s,key):
    q=urllib.parse.urlencode({'symbol':s,'apikey':key})
    with urllib.request.urlopen('https://api.twelvedata.com/quote?'+q,timeout=30) as r:d=json.load(r)
    if 'close' not in d or 'percent_change' not in d:raise RuntimeError(f'Incomplete Twelve Data quote for {s}: {d}')
    close,pct=num(d.get('close')),num(d.get('percent_change')); avg=num(d.get('average_volume')) or num(d.get('avg_volume')) or 0
    return {'close':close,'pct':pct,'open':num(d.get('open')),'high':num(d.get('high')),'low':num(d.get('low')),'volume':num(d.get('volume')) or 0,'avg_volume':avg,'high_52w':num(d.get('fifty_two_week_high')) or close,'premarket_pct':None,'afterhours_pct':None,'timestamp':d.get('timestamp'),'source':'Twelve Data'}
def main():
    key=os.environ.get('TWELVEDATA_KEY')
    if not key:raise SystemExit('TWELVEDATA_KEY is required')
    now=datetime.now(ZoneInfo('America/New_York')); session=now.date().isoformat()
    market_open = now.weekday() < 5 and session not in HOLIDAYS
    quotes={s:quote(s,key) for s in SYMBOLS}; entries=[]
    for s in SYMBOLS:
        q=quotes[s]; pct=q['pct']; sign='up' if pct>=0 else 'down'
        entries.append({'ticker':s,'dir':sign,'strength':'major' if abs(pct)>=5 else 'notable','strength_label':'Large session move' if abs(pct)>=5 else 'Session move','move':f'{pct:+.2f}% close','move_tone':sign,'happened':f'{s} closed at {q["close"]:.2f} on {session}, according to Twelve Data.','figures':[f'Close <b>${q["close"]:.2f}</b>, <b>{pct:+.2f}%</b>',f'Session range <b>${q["low"]:.2f}-${q["high"]:.2f}</b>',f'Volume <b>{q["volume"]:,.0f}</b>; feed average <b>{q["avg_volume"]:,.0f}</b>'],'why':'This is a measured price and volume update. The move alone does not establish why the stock changed or predict the next session.','foot':[{'k':'Price evidence','v':f'Twelve Data quote captured after the {session} US session close.'}]})
    research={}
    research_path=ROOT/'research.json'
    if research_path.exists():
        try: research=json.loads(research_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError: research={}
    upcoming=research.get('upcoming',[]) if isinstance(research,dict) else []
    label='market close' if market_open else 'weekend or market holiday update'
    edition={'date':session,'weekday':now.strftime('%A'),'headline':f'US {label}, {now.strftime("%-d %B %Y")}: prices, news and earnings watch','gauge':[{'text':f'Latest available US market data for {session}' if market_open else f'US markets closed on {session}; latest available prices shown','tone':'flat'}],'quick':[f'<b>{s}</b> {quotes[s]["pct"]:+.2f}% at {quotes[s]["close"]:.2f}' for s in SYMBOLS],'entries':entries,'earnings_ahead':upcoming,'data':{'session':session,'source':'Twelve Data','tickers':quotes}}
    out=ROOT/'editions'/f'{session}.json'
    if out.exists():raise SystemExit(f'refusing to overwrite existing edition: {out.name}')
    out.write_text(json.dumps(edition,indent=2)+'\n',encoding='utf-8');print(out)
if __name__=='__main__':main()
