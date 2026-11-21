from pathlib import Path
from datetime import datetime,timezone
import requests,json,hashlib
import argparse
parser=argparse.ArgumentParser(description='Frozen public ATS discovery; run from repository root and use a new output directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/cohort-ats-history'))
out=parser.parse_args().out;data=[]
for name,url,params in [('weaviate-current','https://api.ashbyhq.com/posting-api/job-board/weaviate',None),('weaviate-cdx','https://web.archive.org/cdx/search/cdx',{'url':'https://jobs.ashbyhq.com/weaviate*','output':'json','filter':'statuscode:200','collapse':'timestamp:6','from':'20251101','to':'20261121','limit':'250'})]:
 p=out/'sources'/(name+'.json');d={'company_id':'weaviate','url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
 if p.exists():raise SystemExit('Refusing overwrite')
 try:
  r=requests.get(url,params=params,timeout=25,headers={'User-Agent':'TrendScout-research/1.0'});p.write_bytes(r.content);d.update(response_url=r.url,http_status=r.status_code,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest());r.raise_for_status();a=r.json()
  if name.endswith('cdx'):d['captures']=[dict(zip(a[0],x)) for x in a[1:]] if a else []
  else:d['job_count']=len(a.get('jobs',[]))
 except (requests.RequestException,ValueError) as e:d['error']=type(e).__name__
 data.append(d)
(out/'weaviate-discovery.json').write_text(json.dumps(data,indent=2)+'\n')
for d in data:print(d.get('file'),d.get('job_count'),len(d.get('captures',[])),d.get('error'))
