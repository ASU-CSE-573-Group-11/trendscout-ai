from pathlib import Path
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import concurrent.futures,requests,json,hashlib
import argparse
parser=argparse.ArgumentParser(description='Public source acquisition; preserve frozen outputs and run new collections in a new directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/remaining-history-discovery'))
out=parser.parse_args().out;sources=json.load(open(out/'archive-discovery.json'));tasks=[]
for source in sources:
 name=source['source_id']
 if name not in ['continue-yc','continue-ashby','wandb-parent','replicate-root']:continue
 a=[c for c in source.get('captures',[]) if not urlsplit(c['original']).query and urlsplit(c['original']).path.rstrip('/') in ['/companies/continue/jobs','/continue','/careers/weights-biases','/about']]
 for c in a[-2:]:tasks.append((name,c))
def fetch(task):
 name,c=task;ts=c['timestamp'];url='https://web.archive.org/web/'+ts+'id_/'+c['original'];d={'source_id':name,'timestamp':ts,'original_url':c['original'],'requested_url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(url,timeout=25);p=out/'sources'/f'{name}-{ts}.html';p.write_bytes(r.content);d.update(http_status=r.status_code,response_url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest());r.raise_for_status();when=parsedate_to_datetime(r.headers['Memento-Datetime']).astimezone(timezone.utc);d.update(memento_datetime=r.headers['Memento-Datetime'],capture_verified=when.strftime('%Y%m%d%H%M%S')==ts,snapshot_at=when.isoformat().replace('+00:00','Z'))
 except (requests.RequestException,ValueError,KeyError) as e:d['error']=type(e).__name__
 return d
if (out/'archive-captures.json').exists():raise SystemExit('Refusing overwrite')
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:a=list(ex.map(fetch,tasks))
(out/'archive-captures.json').write_text(json.dumps(a,indent=2)+'\n')
for d in a:print(d['source_id'],d['timestamp'],d.get('http_status'),d.get('capture_verified'),d.get('error'))
