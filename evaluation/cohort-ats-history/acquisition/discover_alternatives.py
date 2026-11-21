from pathlib import Path
from datetime import datetime,timezone
import concurrent.futures,json,hashlib
import requests
import argparse
parser=argparse.ArgumentParser(description='Frozen public ATS discovery; run from repository root and use a new output directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/cohort-ats-history'))
out=parser.parse_args().out; tasks=[('browserbase','https://job-boards.greenhouse.io/browserbaseinc*'),('sourcegraph','https://job-boards.greenhouse.io/sourcegraph91*'),('deepset','https://jobs.ashbyhq.com/deepsetai/*'),('crewai','https://apply.workable.com/api/v1/widget/accounts/crewai*')]
def fetch(task):
 cid,target=task;d={'company_id':cid,'target_url':target,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get('https://web.archive.org/cdx/search/cdx',params={'url':target,'output':'json','filter':'statuscode:200','collapse':'timestamp:6','from':'20251101','to':'20261121','limit':'250'},timeout=25);p=out/'sources'/f'{cid}-alternate-cdx.json';p.write_bytes(r.content);d.update(http_status=r.status_code,response_url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest());r.raise_for_status();a=r.json();d['captures']=[dict(zip(a[0],x)) for x in a[1:]] if a else []
 except (requests.RequestException,ValueError) as e:d['error']=type(e).__name__
 return d
if (out/'remaining-board-search.json').exists():raise SystemExit('Refusing overwrite')
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:a=list(ex.map(fetch,tasks))
(out/'remaining-board-search.json').write_text(json.dumps(a,indent=2)+'\n')
for c in a:print(c['company_id'],len(c.get('captures',[])),c.get('error'),[(x['timestamp'],x['original']) for x in c.get('captures',[])][:2])
