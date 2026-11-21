import requests,json,hashlib
from datetime import datetime,timezone
from pathlib import Path
import argparse
parser=argparse.ArgumentParser(description='Public source acquisition; preserve frozen outputs and run new collections in a new directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/remaining-history-discovery'))
out=parser.parse_args().out;tasks={'wandb-current':'https://boards-api.greenhouse.io/v1/boards/weights_and_biases/jobs?content=true','wandb-legacy-cdx':'https://boards.greenhouse.io/weights_and_biases*','wandb-modern-cdx':'https://job-boards.greenhouse.io/weights_and_biases*'};a=[]
if (out/'wandb-discovery.json').exists():raise SystemExit('Refusing overwrite')
for key,url in tasks.items():
 d={'source_id':key,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  if key.endswith('cdx'):r=requests.get('https://web.archive.org/cdx/search/cdx',params={'url':url,'output':'json','filter':'statuscode:200','collapse':'timestamp:6','from':'20251101','to':'20261121','limit':'250'},timeout=25)
  else:r=requests.get(url,timeout=25)
  p=out/'sources'/(key+'.json');p.write_bytes(r.content);d.update(url=r.url,http_status=r.status_code,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest());r.raise_for_status();x=r.json()
  if key.endswith('cdx'):d['captures']=[dict(zip(x[0],row)) for row in x[1:]] if x else []
  else:d['job_count']=len(x.get('jobs',[]))
 except (requests.RequestException,ValueError) as e:d['error']=type(e).__name__
 a.append(d)
(out/'wandb-discovery.json').write_text(json.dumps(a,indent=2)+'\n')
for d in a:print(d['source_id'],d.get('job_count'),len(d.get('captures',[])),d.get('error'))
