import concurrent.futures,hashlib,json,re
from pathlib import Path
from datetime import datetime,timezone
import requests
import argparse
parser=argparse.ArgumentParser(description='Collect public career discovery evidence into a new frozen directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/cohort-history-followup'))
out=parser.parse_args().out
if (out/'discovery.json').exists(): raise SystemExit("Refusing to overwrite this frozen acquisition; use a new directory.")
out.mkdir(parents=True,exist_ok=True)
(out/"sources").mkdir(exist_ok=True)
urls={'llamaindex':'https://www.llamaindex.ai/careers','crewai':'https://apply.workable.com/crewai/','continue':'https://www.continue.dev/','weaviate':'https://weaviate.io/company/careers','chroma':'https://www.trychroma.com/careers','arize':'https://arize.com/careers/','langfuse':'https://langfuse.com/careers','replicate':'https://replicate.com/careers','wandb':'https://wandb.ai/site/careers/'}
def fetch(item):
 cid,url=item; d={'company_id':cid,'url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(url,timeout=20,headers={'User-Agent':'TrendScout-research/1.0'});p=out/'sources'/f'{cid}-careers.html';p.write_bytes(r.content);d.update(status=r.status_code,response_url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest());text=r.text.replace('\\/','/').replace('&amp;','&');d['ats_links']=sorted(set(re.findall(r'https?://[^\s<>"\x27\\]*(?:ashbyhq|greenhouse\.io|workable\.com|lever\.co)[^\s<>"\x27\\]*',text)));d['dated_fragments']=re.findall(r'.{0,40}202[56]-\d\d-\d\d.{0,40}',text)[:4]
 except requests.RequestException as e:d['error']=type(e).__name__
 return d
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex: data=list(ex.map(fetch,urls.items()))
(out/'discovery.json').write_text(json.dumps(data,indent=2)+'\n')
for x in data:print(x['company_id'],x.get('status'),x.get('ats_links'),x.get('error'))
