import concurrent.futures,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
import requests
import argparse
parser=argparse.ArgumentParser(description='Collect public career discovery evidence into a new frozen directory.')
parser.add_argument('--out',type=Path,default=Path('evaluation/cohort-history-followup'))
out=parser.parse_args().out
if (out/'archive-search.json').exists(): raise SystemExit("Refusing to overwrite this frozen acquisition; use a new directory.")
out.mkdir(parents=True,exist_ok=True)
(out/"sources").mkdir(exist_ok=True)
initial=json.loads((out/'discovery.json').read_text());urls={x['company_id']:x['url'] for x in initial};old=json.load(open('evaluation/cohort-source-audit/board-audit.json'))
for c in old['companies']:
 if c['company_id'] in ['langchain','modal']:continue
 for b in c['boards']:urls[c['company_id']]=b['api_url']
# In addition to APIs, retain official HTML history discovery for absent boards.
query=[(c,u) for c,u in urls.items() if c not in ['langchain','modal']]
def fetch(item):
 cid,url=item;entry={'company_id':cid,'target_url':url,'checked_at':datetime.now(timezone.utc).isoformat()};params={'url':url.rstrip('/')+'*','output':'json','filter':'statuscode:200','collapse':'timestamp:6','from':'20251101','to':'20261121','limit':'250'}
 try:
  r=requests.get('https://web.archive.org/cdx/search/cdx',params=params,timeout=25,headers={'User-Agent':'TrendScout-research/1.0'});p=out/'sources'/f'{cid}-cdx.json';p.write_bytes(r.content);entry.update(http_status=r.status_code,url=r.url,file=str(p.relative_to(out)),sha256=hashlib.sha256(r.content).hexdigest());r.raise_for_status();rows=r.json();entry['captures']=[dict(zip(rows[0],a)) for a in rows[1:]] if rows else [];entry['scope']='Prefix lookup; captures may include individual roles, filtered pages or unavailable payloads. No complete board or historical stock is inferred.'
 except (requests.RequestException,ValueError) as e:entry['error']=type(e).__name__
 return entry
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:data=list(ex.map(fetch,query))
(out/'archive-search.json').write_text(json.dumps(data,indent=2)+'\n')
for x in data:print(x['company_id'],len(x.get('captures',[])),x.get('error'),[(r['timestamp'],r['original']) for r in x.get('captures',[])][:3])
