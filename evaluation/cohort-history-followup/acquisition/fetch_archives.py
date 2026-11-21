import concurrent.futures,json,hashlib
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import requests
import argparse
parser=argparse.ArgumentParser(description='Collect public career discovery evidence into a new frozen directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/cohort-history-followup'))
out=parser.parse_args().out
if (out/'archive-captures.json').exists(): raise SystemExit("Refusing to overwrite this frozen acquisition; use a new directory.")
out.mkdir(parents=True,exist_ok=True)
(out/"sources").mkdir(exist_ok=True)
lookup=json.load(open(out/'archive-search.json'));tasks=[]
for c in lookup:
 if c['company_id'] not in ['llamaindex','arize','weaviate','chroma','crewai']:continue
 a=[r for r in c.get('captures',[]) if urlsplit(r['original']).path.rstrip('/')==urlsplit(c['target_url']).path.rstrip('/') and not urlsplit(r['original']).query]
 for r in a[-2:]:tasks.append((c['company_id'],r))
def fetch(task):
 cid,row=task;ts=row['timestamp'];url='https://web.archive.org/web/'+ts+'id_/'+row['original'];d={'company_id':cid,'requested_url':url,'timestamp':ts,'original_url':row['original'],'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(url,timeout=30,headers={'User-Agent':'TrendScout-research/1.0'});p=out/'sources'/f'{cid}-{ts}.html';p.write_bytes(r.content);d.update(http_status=r.status_code,response_url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest(),memento_datetime=r.headers.get('Memento-Datetime'));r.raise_for_status();clock=parsedate_to_datetime(r.headers['Memento-Datetime']).astimezone(timezone.utc);d['capture_verified']=clock.strftime('%Y%m%d%H%M%S')==ts;d['snapshot_at']=clock.isoformat().replace('+00:00','Z')
 except (requests.RequestException,ValueError,KeyError) as e:d['error']=type(e).__name__
 return d
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex: data=list(ex.map(fetch,tasks))
(out/'archive-captures.json').write_text(json.dumps(data,indent=2)+'\n')
for r in data:print(r['company_id'],r['timestamp'],r.get('http_status'),r.get('capture_verified'),r.get('error'))
