import json,hashlib,requests,concurrent.futures
from pathlib import Path
from datetime import datetime,timezone
import argparse
parser=argparse.ArgumentParser(description='Public source acquisition; preserve frozen outputs and run new collections in a new directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/remaining-history-discovery'))
out=parser.parse_args().out;out.mkdir(exist_ok=True);(out/'sources').mkdir(exist_ok=True)
urls={
 'continue-about':'https://www.continue.dev/about',
 'continue-careers':'https://www.continue.dev/careers',
 'continue-yc':'https://www.ycombinator.com/companies/continue/jobs',
 'crewai-widget':'https://apply.workable.com/api/v1/widget/accounts/crewai',
 'crewai-llms':'https://apply.workable.com/crewai/llms.txt',
 'crewai-client':'https://dcvxs6ggqztsa.cloudfront.net/candidate/releases/advanced.f944702957ef865c.js',
 'langfuse-parent':'https://clickhouse.com/company/careers?search=langfuse',
 'wandb-parent':'https://coreweave.com/careers/weights-biases',
 'replicate-parent':'https://www.cloudflare.com/careers/'
}
def fetch(pair):
 name,url=pair;r0={'source_id':name,'url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(url,timeout=20,headers={'User-Agent':'TrendScout-research/1.0'});p=out/'sources'/(name+'.txt');p.write_bytes(r.content);r0.update(status=r.status_code,response_url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest())
 except requests.RequestException as e:r0['error']=type(e).__name__
 return r0
if (out/'discovery.json').exists():raise SystemExit('Refusing overwrite')
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:a=list(ex.map(fetch,urls.items()))
(out/'discovery.json').write_text(json.dumps(a,indent=2)+'\n')
for r in a:print(r['source_id'],r.get('status'),r.get('error'))
