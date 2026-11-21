from pathlib import Path
import concurrent.futures,json,hashlib
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import requests
import argparse
parser=argparse.ArgumentParser(description='Frozen public ATS discovery; run from repository root and use a new output directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/cohort-ats-history'))
out=parser.parse_args().out;tasks=[]
for c in json.load(open(out/'discovery.json')):
 a=[r for r in c.get('captures',[]) if urlsplit(r['original']).path.rstrip('/')==urlsplit(c['board_url']).path.rstrip('/') and not urlsplit(r['original']).query]
 for row in a[-2:]:tasks.append((c['company_id'],row))
def fetch(task):
 cid,row=task;ts=row['timestamp'];url='https://web.archive.org/web/'+ts+'id_/'+row['original'];d={'company_id':cid,'timestamp':ts,'original_url':row['original'],'requested_url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(url,timeout=25,headers={'User-Agent':'TrendScout-research/1.0'});p=out/'sources'/f'{cid}-{ts}.html';p.write_bytes(r.content);d.update(http_status=r.status_code,response_url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest(),memento_datetime=r.headers.get('Memento-Datetime'));r.raise_for_status();when=parsedate_to_datetime(r.headers['Memento-Datetime']).astimezone(timezone.utc);d.update(capture_verified=when.strftime('%Y%m%d%H%M%S')==ts,snapshot_at=when.isoformat().replace('+00:00','Z'))
 except (requests.RequestException,ValueError,KeyError) as e:d['error']=type(e).__name__
 return d
if (out/'captures.json').exists():raise SystemExit('Refusing overwrite')
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:data=list(ex.map(fetch,tasks))
(out/'captures.json').write_text(json.dumps(data,indent=2)+'\n')
for x in data:print(x['company_id'],x['timestamp'],x.get('http_status'),x.get('capture_verified'),x.get('error'))
