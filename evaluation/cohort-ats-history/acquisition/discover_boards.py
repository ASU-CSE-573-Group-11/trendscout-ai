from pathlib import Path
import concurrent.futures,json,hashlib
from datetime import datetime,timezone
import requests
import argparse
parser=argparse.ArgumentParser(description='Frozen public ATS discovery; run from repository root and use a new output directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/cohort-ats-history'))
out=parser.parse_args().out;out.mkdir(exist_ok=True);(out/'sources').mkdir(exist_ok=True)
boards=json.load(open('evaluation/cohort-source-audit/board-audit.json'));tasks=[]
for c in boards['companies']:
 if c['company_id'] in ['langchain','modal']:continue
 for b in c['boards']:
  host='https://jobs.ashbyhq.com/' if b['type']=='ashby' else 'https://boards.greenhouse.io/'
  tasks.append((c['company_id'],host+b['slug'],b['type']))
def fetch(task):
 cid,url,kind=task;d={'company_id':cid,'board_type':kind,'board_url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get('https://web.archive.org/cdx/search/cdx',params={'url':url+'*','output':'json','filter':'statuscode:200','collapse':'timestamp:6','from':'20251101','to':'20261121','limit':'250'},timeout=25,headers={'User-Agent':'TrendScout-research/1.0'});p=out/'sources'/f'{cid}-cdx.json';p.write_bytes(r.content);d.update(http_status=r.status_code,url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest());r.raise_for_status();a=r.json();d['captures']=[dict(zip(a[0],x)) for x in a[1:]] if a else []
 except (requests.RequestException,ValueError) as e:d['error']=type(e).__name__
 return d
if (out/'discovery.json').exists():raise SystemExit('Refusing overwrite')
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:data=list(ex.map(fetch,tasks))
(out/'discovery.json').write_text(json.dumps(data,indent=2)+'\n')
for x in data:print(x['company_id'],len(x.get('captures',[])),x.get('error'),[(c['timestamp'],c['original']) for c in x.get('captures',[])][:2])
