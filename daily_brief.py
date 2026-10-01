#!/usr/bin/env python3
import json, os, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).parent
symbols=['AAPL','AMZN','TSLA','PLTR','MSFT','GOOGL','HOOD','NVDA','INTC','NBIS','MRVL','META']
key=os.environ.get('TWELVEDATA_KEY')
if not key: raise SystemExit('TWELVEDATA_KEY is required')
def quote(s):
 q=urllib.parse.urlencode({'symbol':s,'apikey':key})
 with urllib.request.urlopen('https://api.twelvedata.com/quote?'+q,timeout=30) as r: d=json.load(r)
 if 'close' not in d: raise RuntimeError(f'No quote for {s}: {d}')
 return d
now=datetime.now(timezone.utc); date=now.date().isoformat()
t=max((ROOT/'editions').glob('*.json'),key=lambda p:p.name); e=json.loads(t.read_text())
qs={s:quote(s) for s in symbols}; e['date']=date; e['weekday']=now.strftime('%A'); e['headline']=f'Market snapshot, {now:%d %b %Y}'
e['data']={'session':date,'source':'Twelve Data','tickers':symbols,'raw_quotes':qs}
e['quick']=[f"{s}: {qs[s].get('close')} ({qs[s].get('percent_change','n/a')}%)" for s in symbols]
for x in e.get('entries',[]):
 s=x.get('ticker')
 if s in qs:
  q=qs[s]; x['move']=f"{q.get('percent_change','n/a')}%"; x['happened']=f"Latest Twelve Data quote: {q.get('close')} at {q.get('timestamp',date)}."; x['figures']=[f"Close: {q.get('close')}",f"Change: {q.get('percent_change','n/a')}%"]
(ROOT/'editions'/f'{date}.json').write_text(json.dumps(e,indent=2)+'
')
print(date)
