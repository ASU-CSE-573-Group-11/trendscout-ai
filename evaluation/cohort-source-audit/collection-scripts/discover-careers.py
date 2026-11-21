import requests,json,re,hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
cohort=json.loads(Path('data/registry/cohort.json').read_text())
p=Path('evaluation/cohort-source-audit');p.mkdir(exist_ok=False);(p/'sources').mkdir()
paths={'langchain':'https://www.langchain.com/careers','llamaindex':'https://www.llamaindex.ai/careers','crewai':'https://www.crewai.com/careers','e2b':'https://e2b.dev/careers','browserbase':'https://www.browserbase.com/careers','composio':'https://composio.dev/careers','letta':'https://www.letta.com/careers','langfuse':'https://langfuse.com/careers','deepset':'https://www.deepset.ai/careers','continue':'https://www.continue.dev/careers','sourcegraph':'https://sourcegraph.com/jobs','modal':'https://modal.com/company','replicate':'https://replicate.com/about','wandb':'https://site.wandb.ai/careers/','pinecone':'https://www.pinecone.io/careers/','weaviate':'https://weaviate.io/company/careers','chroma':'https://www.trychroma.com/careers','arize':'https://arize.com/careers/'}
def one(c):
 cid=c['company_id'];url=paths[cid];result={'company_id':cid,'requested_url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(url,timeout=30,headers={'User-Agent':'TrendScout-research/1.0'});result.update(response_url=r.url,status_code=r.status_code)
  filename='sources/'+cid+'.html';(p/filename).write_bytes(r.content);result.update(file=filename,sha256=hashlib.sha256(r.content).hexdigest())
  text=r.text.replace('\\/','/').replace('&amp;','&')
  matches=re.findall(r'https://(?:jobs\.ashbyhq\.com|(?:job-boards|boards)\.greenhouse\.io|jobs\.lever\.co|[a-z0-9-]+\.jobs\.personio\.(?:com|de))[^\s"<>\\]*',text)
  result['board_links']=sorted(set(matches)) if r.status_code==200 else []
 except requests.RequestException as e:result.update(error=type(e).__name__,board_links=[])
 print(cid,result.get('status_code'),result['board_links'][:5],flush=True);return result
with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(one,cohort['companies']))
(p/'careers-discovery.json').write_text(json.dumps({'sources':results,'scope':'Links discovered on official company pages; links alone do not certify historical board completeness.'},indent=2)+'\n')
