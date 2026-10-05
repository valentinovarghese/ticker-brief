import json,sys
from pathlib import Path
import charts
if len(sys.argv)!=2 or sys.argv[1] not in charts.TICKERS: raise SystemExit('usage: refresh_live.py TICKER')
t=sys.argv[1]; rows=charts._from_twelvedata(t,'1min')
if not rows: raise SystemExit('no intraday data returned')
rows=charts.drop_incomplete(rows); series={'1m':[list(r) for r in rows[-390:]]}
for label,m in [('3m',3),('5m',5),('15m',15),('30m',30),('1h',60)]: series[label]=[list(r) for r in charts.aggregate(rows,m)[-470:]]
out=Path('charts/live'); out.mkdir(parents=True,exist_ok=True)
(out/f'{t}.json').write_text(json.dumps({'ticker':t,'updated':rows[-1][0],'series':series},separators=(',',':')))

