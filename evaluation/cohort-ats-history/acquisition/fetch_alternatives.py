import json,requests,hashlib,concurrent.futures
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import argparse
parser=argparse.ArgumentParser(description='Frozen public ATS discovery; run from repository root and use a new output directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/cohort-ats-history'))
out=parser.parse_args().out;tasks=[]
for c in json.load(open(out/'remaining-board-search.json')):
 a=[r for r in c.get('captures',[]) if urlsplit(r['original']).path.rstrip('/') in ['/browserbaseinc','/sourcegraph91','/deepsetai'] and not urlsplit(r['original']).query]
 for r in a[-2:]:tasks.append((c['company_id'],r))
def fetch(task):
 cid,c=task;ts=c['timestamp'];u='https://web.archive.org/web/'+ts+'id_/'+c['original'];d={'company_id':cid,'timestamp':ts,'original_url':c['original'],'requested_url':u,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(u,timeout=25);r.raise_for_status();p=out/'sources'/f'{cid}-{ts}.html';p.write_bytes(r.content);when=parsedate_to_datetime(r.headers['Memento-Datetime']).astimezone(timezone.utc);d.update(http_status=r.status_code,response_url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest(),memento_datetime=r.headers['Memento-Datetime'],capture_verified=when.strftime('%Y%m%d%H%M%S')==ts,snapshot_at=when.isoformat().replace('+00:00','Z'))
 except (requests.RequestException,ValueError,KeyError) as e:d['error']=type(e).__name__
 return d
if (out/'alternate-captures.json').exists():raise SystemExit('Refusing overwrite')
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:a=list(ex.map(fetch,tasks))
(out/'alternate-captures.json').write_text(json.dumps(a,indent=2)+'\n')
for c in a:print(c['company_id'],c['timestamp'],c.get('http_status'),c.get('capture_verified'),c.get('error'))
