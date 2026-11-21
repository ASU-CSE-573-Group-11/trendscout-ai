import json,hashlib,requests,re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
p=Path('evaluation/cohort-archive-followup');p.mkdir(exist_ok=False);(p/'sources').mkdir()
audit=json.loads(Path('evaluation/cohort-source-audit/board-audit.json').read_text())
boards=[{'company_id':c['company_id'],**b} for c in audit['companies'] for b in c['boards']]
boards.append({'company_id':'llamaindex','type':'ashby','api_url':'https://api.ashbyhq.com/posting-api/job-board/llamaindex','link_evidence':'https://jobs.ashbyhq.com/llamaindex/156d7573-82dd-4973-87ab-7d5a056650d5'})
def one(b):
 cid=b['company_id'];o={'company_id':cid,'api_url':b['api_url'],'mapping_evidence':b['link_evidence'],'checked_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get('https://web.archive.org/cdx/search/cdx',params={'url':b['api_url']+'*','output':'json','filter':'statuscode:200','collapse':'timestamp:8','from':'20251101','to':'20261121','limit':'128'},timeout=40);r.raise_for_status()
  f='sources/'+cid+'-prefix-cdx.json';(p/f).write_bytes(r.content)
  rows=r.json();o.update(source_url=r.url,file=f,sha256=hashlib.sha256(r.content).hexdigest(),captures=[dict(zip(rows[0],row)) for row in rows[1:]] if rows else [])
 except (requests.RequestException,ValueError) as e:o['lookup_error']=type(e).__name__
 print(cid,len(o.get('captures',[])),o.get('lookup_error',''),flush=True);return o
with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(one,boards))
extras={
'weaviate-script':'https://weaviate.io/assets/js/main.8ff63803.js',
'crewai-home':'https://www.crewai.com/',
'continue-home':'https://www.continue.dev/',
'llamaindex-board':'https://jobs.ashbyhq.com/llamaindex/156d7573-82dd-4973-87ab-7d5a056650d5'}
pages=[]
for name,url in extras.items():
 o={'source_url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
 try:
  r=requests.get(url,timeout=30);r.raise_for_status();f='sources/'+name+'.txt';(p/f).write_bytes(r.content);o.update(file=f,sha256=hashlib.sha256(r.content).hexdigest(),response_url=r.url)
  body=r.text.replace('\\/','/')
  o['ats_links']=sorted(set(re.findall(r'https://(?:jobs\.ashbyhq\.com|apply\.workable\.com|jobs\.lever\.co|(?:job-boards|boards)\.greenhouse\.io)[^\s"<>\\]*',body)))
  print(name,o['ats_links'][:8],flush=True)
 except requests.RequestException as e:o['lookup_error']=type(e).__name__
 pages.append(o)
(p/'manifest.json').write_text(json.dumps({'boards':results,'additional_mapping_sources':pages,'scope':'Additional prefix/query-variant CDX search inside the study window. Lookup failure or no captures means unavailable coverage, not zero jobs. Search results are not normalized board observations.'},indent=2)+'\n')
