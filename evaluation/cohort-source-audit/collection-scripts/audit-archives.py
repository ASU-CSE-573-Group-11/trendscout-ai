import json,requests,re,hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from datetime import datetime,timezone
p=Path('evaluation/cohort-source-audit');d=json.loads((p/'careers-discovery.json').read_text())
def one(s):
 cid=s['company_id'];boards=[]
 for link in s['board_links']:
  parsed=urlparse(link); slug=parsed.path.strip('/').split('/')[0]
  if parsed.hostname=='jobs.ashbyhq.com': url='https://api.ashbyhq.com/posting-api/job-board/'+slug;typ='ashby'
  elif parsed.hostname in ['job-boards.greenhouse.io','boards.greenhouse.io']:url='https://boards-api.greenhouse.io/v1/boards/'+slug+'/jobs';typ='greenhouse'
  else:continue
  if url not in [b['api_url'] for b in boards]:boards.append({'type':typ,'slug':slug,'api_url':url,'link_evidence':link})
 result={'company_id':cid,'official_page_file':s.get('file'),'boards':boards}
 for i,b in enumerate(boards):
  b['checked_at']=datetime.now(timezone.utc).isoformat()
  try:
   r=requests.get(b['api_url'],timeout=35);b['current_http_status']=r.status_code
   f='sources/'+cid+'-board-'+str(i)+'.json';(p/f).write_bytes(r.content);b.update(current_file=f,current_sha256=hashlib.sha256(r.content).hexdigest())
   if r.status_code==200:
    data=r.json();jobs=data.get('jobs');b['current_listed_count']=len([j for j in jobs if j.get('isListed',True)]) if isinstance(jobs,list) else None
   r=requests.get('https://web.archive.org/cdx/search/cdx',params={'url':b['api_url'],'output':'json','filter':'statuscode:200','collapse':'timestamp:6','from':'2025','to':'2026','limit':'24'},timeout=35)
   r.raise_for_status();data=r.json();f='sources/'+cid+'-cdx-'+str(i)+'.json';(p/f).write_bytes(r.content);b.update(cdx_file=f,cdx_sha256=hashlib.sha256(r.content).hexdigest(),cdx_url=r.url)
   b['captures']=[dict(zip(data[0],row)) for row in data[1:]] if data else []
  except (requests.RequestException,ValueError,TypeError) as e:b['error']=type(e).__name__
 print(cid,[(b['slug'],b.get('current_listed_count'),len(b.get('captures',[])),b.get('error')) for b in boards],flush=True)
 return result
with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(one,d['sources']))
(p/'board-audit.json').write_text(json.dumps({'companies':results,'scope':'Board mapping from official page links; CDX search coverage is not proof that no other historical source exists. Empty board capture lists are missing data, not zero postings.'},indent=2)+'\n')
