from pathlib import Path
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import requests,json,hashlib,concurrent.futures
import argparse
parser=argparse.ArgumentParser(description='Public source acquisition; preserve frozen outputs and run new collections in a new directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/remaining-history-discovery'))
out=parser.parse_args().out;tasks=[]
a=next(x for x in json.load(open(out/'parent-board-discovery.json')) if x['source_id']=='clickhouse-ashby-cdx')['captures']
a=[c for c in a if urlsplit(c['original']).path.rstrip('/')=='/clickhouse' and not urlsplit(c['original']).query]
for c in a[-2:]:tasks.append(('langfuse-parent-board',c))
old=next(x for x in json.load(open('evaluation/cohort-history-followup/archive-search.json')) if x['company_id']=='crewai')['captures']
for code in ['3862836931','201DADAE3F']:
 candidates=[c for c in old if '/j/'+code in c['original']]
 if candidates:tasks.append(('crewai-individual-role',candidates[-1]))
def fetch(task):
 name,c=task;ts=c['timestamp'];u='https://web.archive.org/web/'+ts+'id_/'+c['original'];d={'source_id':name,'timestamp':ts,'original_url':c['original'],'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(u,timeout=25);p=out/'sources'/f'{name}-{ts}.html';p.write_bytes(r.content);d.update(http_status=r.status_code,response_url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest());r.raise_for_status();when=parsedate_to_datetime(r.headers['Memento-Datetime']).astimezone(timezone.utc);d.update(memento_datetime=r.headers['Memento-Datetime'],capture_verified=when.strftime('%Y%m%d%H%M%S')==ts,snapshot_at=when.isoformat().replace('+00:00','Z'))
 except (requests.RequestException,ValueError,KeyError) as e:d['error']=type(e).__name__
 return d
if (out/'extra-archive-captures.json').exists():raise SystemExit('Refusing overwrite')
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:data=list(ex.map(fetch,tasks))
(out/'extra-archive-captures.json').write_text(json.dumps(data,indent=2)+'\n')
for r in data:print(r['source_id'],r['timestamp'],r.get('http_status'),r.get('capture_verified'),r.get('error'))
