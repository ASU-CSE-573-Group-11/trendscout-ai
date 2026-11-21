from pathlib import Path
from datetime import datetime,timezone
import requests,json,hashlib,concurrent.futures
import argparse
parser=argparse.ArgumentParser(description='Public source acquisition; preserve frozen outputs and run new collections in a new directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/remaining-history-discovery'))
out=parser.parse_args().out
tasks={'continue-yc':'https://www.ycombinator.com/companies/continue/jobs*','continue-ashby':'https://jobs.ashbyhq.com/continue*','crewai-md':'https://apply.workable.com/crewai/jobs.md*','crewai-llms':'https://apply.workable.com/crewai/llms.txt*','langfuse-canonical':'https://langfuse.com/careers*','wandb-parent':'https://www.coreweave.com/careers/weights-biases*','replicate-root':'https://replicate.com/about*'}
def fetch(pair):
 name,url=pair;d={'source_id':name,'target_url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get('https://web.archive.org/cdx/search/cdx',params={'url':url,'output':'json','filter':'statuscode:200','collapse':'timestamp:6','from':'20251101','to':'20261121','limit':'250'},timeout=25);p=out/'sources'/(name+'-cdx.json');p.write_bytes(r.content);d.update(http_status=r.status_code,response_url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest());r.raise_for_status();a=r.json();d['captures']=[dict(zip(a[0],v)) for v in a[1:]] if a else []
 except (requests.RequestException,ValueError) as e:d['error']=type(e).__name__
 return d
if (out/'archive-discovery.json').exists():raise SystemExit('Refusing overwrite')
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:a=list(ex.map(fetch,tasks.items()))
(out/'archive-discovery.json').write_text(json.dumps(a,indent=2)+'\n')
for d in a:print(d['source_id'],len(d.get('captures',[])),d.get('error'),[(c['timestamp'],c['original']) for c in d.get('captures',[])][:2])
