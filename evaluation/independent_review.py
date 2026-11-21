"""Blind source-review collection; source-assisted workbooks are never prefilled."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit

from collectors.records import utc_now
from evaluation.compute_agreement import cohen_kappa

ROOT=Path(__file__).resolve().parents[1]
NAMES={'sueda':'Sueda Sen','mehmet':'Mehmet'}
LOCK=threading.Lock()


def fingerprint(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def context(round_name,root=ROOT):
    if round_name not in {'real','mixed'}:raise ValueError('Unknown frozen round')
    base=root/'evaluation'/round_name
    pool='sueda-review/candidate-review-v2/candidates.json' if round_name=='real' and (base/'sueda-review/candidate-review-v2/candidates.json').exists() else 'candidate-items.json'
    candidates=json.loads((base/pool).read_text())
    records={r['record_id']:r for r in (json.loads(line) for line in (base/'records.jsonl').read_text().splitlines() if line.strip())}
    guide=json.loads((base/'guidelines.json').read_text())
    binding={n:fingerprint(base/n) for n in ['manifest.json',pool,'records.jsonl','guidelines.json']}
    return base,candidates,records,guide,binding


def path_for(root,round_name,reviewer):
    if reviewer not in NAMES:raise ValueError('Unknown reviewer')
    return root/'evaluation/independent-review'/round_name/'direct'/(reviewer+'.json')


def load_review(root,round_name,reviewer,binding):
    p=path_for(root,round_name,reviewer)
    if not p.exists():return {'reviewer':reviewer,'round':round_name,'source_sha256':binding,'decisions':{'entities':{},'relations':{}}}
    data=json.loads(p.read_text())
    if data.get('method')!='direct_source_decisions_with_reviewer_self_reported_independence':
        raise ValueError('Direct review store contains non-independent assisted records; preserve and reconcile before collecting personal decisions')
    if data['source_sha256']!=binding:raise ValueError('Frozen source changed; review requires reconciliation')
    return data


def next_item(round_name,reviewer,kind,root=ROOT):
    if kind not in {'entities','relations'}:raise ValueError('Unknown item type')
    base,items,records,guide,binding=context(round_name,root)
    data=load_review(root,round_name,reviewer,binding)
    remaining=[c for c in items[kind] if c['item_id'] not in data['decisions'][kind]]
    allowed=list(guide['entity_types' if kind=='entities' else 'relation_types'])+['NONE']
    result={'reviewer':NAMES[reviewer],'kind':kind,'completed':len(data['decisions'][kind]),'total':len(items[kind]),'labels':allowed}
    if not remaining:return dict(result,finished=True)
    candidate={k:v for k,v in remaining[0].items() if k not in {'label','notes'}}
    doc=records[candidate['document_id']]
    return dict(result,finished=False,candidate=candidate,source={'title':doc['title'],'url':doc['source_url'],'text':doc['text'],'event_at':doc.get('event_at'),'published_at':doc.get('published_at'),'observed_at':doc.get('observed_at')})


def record(payload,root=ROOT):
    round_name=payload['round'];reviewer=payload['reviewer'];kind=payload['kind']
    if kind not in {'entities','relations'}:raise ValueError('Unknown item type')
    if payload.get('personal_independence_confirmation') is not True:
        raise ValueError('A personal review confirmation is required for each saved decision')
    base,items,records,guide,binding=context(round_name,root)
    expected={c['item_id'] for c in items[kind]}
    label=payload.get('label');item_id=payload.get('item_id')
    if item_id not in expected or label not in set(guide['entity_types' if kind=='entities' else 'relation_types'])|{'NONE'}:
        raise ValueError('Unknown item or invalid/missing label')
    with LOCK:
        data=load_review(root,round_name,reviewer,binding)
        if item_id in data['decisions'][kind]:raise ValueError('Decision already recorded; explicit reconciliation is required to revise it')
        data['decisions'][kind][item_id]={'label':label,'notes':str(payload.get('notes',''))[:4000],
            'recorded_at':utc_now(),'personal_independence_confirmation':True}
        data['method']='direct_source_decisions_with_reviewer_self_reported_independence'
        data['identity_basis']='Reviewer selected their own team identity; no external identity verification is claimed.'
        data['updated_at']=utc_now()
        data['complete']=all(len(data['decisions'][k])==len(items[k]) for k in ['entities','relations'])
        p=path_for(root,round_name,reviewer);p.parent.mkdir(parents=True,exist_ok=True)
        temp=p.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n');temp.replace(p)
    return {'saved':True,'complete':data['complete']}


def agreement(round_name,root=ROOT):
    base,items,records,guide,binding=context(round_name,root)
    reviewers=[load_review(root,round_name,r,binding) for r in NAMES]
    result={}
    for kind in ['entities','relations']:
        expected={c['item_id'] for c in items[kind]};allowed=set(guide['entity_types' if kind=='entities' else 'relation_types'])|{'NONE'}
        labels=[]
        for data in reviewers:
            decisions=data['decisions'][kind]
            if set(decisions)!=expected:raise ValueError(f"{data['reviewer']} {kind}: {len(decisions)}/{len(expected)} actual decisions recorded")
            if any(v['label'] not in allowed or v.get('personal_independence_confirmation') is not True or not v.get('recorded_at') for v in decisions.values()):raise ValueError('Invalid personal review record')
            labels.append({k:v['label'] for k,v in decisions.items()})
        a,b=labels;degenerate=len(set(a.values())|set(b.values()))==1
        kappa,n=(None,len(expected)) if degenerate else cohen_kappa(a,b)
        result[kind]={'shared_items':n,'cohen_kappa':kappa,'undefined_reason':'single category' if degenerate else None,
            'raw_agreement':sum(a[k]==b[k] for k in expected)/len(expected),'disagreements':[k for k in sorted(expected) if a[k]!=b[k]]}
    return {'round':round_name,'source_sha256':binding,'review_file_sha256':{r:fingerprint(path_for(root,round_name,r)) for r in NAMES},
        'method':'Two separately saved source reviews; independence is reviewer self-reported, not externally verified.','results':result}


def status(round_name,root=ROOT):
    base,items,records,guide,binding=context(round_name,root)
    reviewers={}
    for name in NAMES:
        data=load_review(root,round_name,name,binding)
        reviewers[name]={kind:{'recorded':len(data['decisions'][kind]),'required':len(items[kind])} for kind in ['entities','relations']}
    complete=all(x['recorded']==x['required'] for r in reviewers.values() for x in r.values())
    result=agreement(round_name,root) if complete else None
    assisted=[str(p.relative_to(root)) for p in (root/'evaluation/independent-review'/round_name).glob('*.json')]
    return {'assisted_records_preserved_outside_direct_store':assisted,'candidate_source_files':list(binding),'status':'complete_for_pairwise_agreement' if result else 'requires_personal_decisions',
            'reviewers':reviewers,'pairwise_agreement':result,
            'scope':'Direct source decisions, independence self-reported; assisted worksheets and source supplements are separate.'}


HTML='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Independent source review</title>
<style>body{font:17px system-ui;max-width:960px;margin:36px auto;padding:0 20px;color:#172635}select,button,textarea{font:inherit;padding:10px;margin:8px 6px 8px 0}pre{white-space:pre-wrap;background:#f0f4f8;padding:20px;line-height:1.5}#text{max-height:340px;overflow:auto}#candidate{font:600 19px system-ui}textarea{box-sizing:border-box;max-width:100%}label{display:block;margin:16px 0}#message{color:#873400}mark{background:#ffe18a}button{cursor:pointer}</style>
<h1>Independent source review</h1><p>Choose your own identity. Review the cited source without consulting the other reviewer's decisions or prepared labels. No answers are preselected. Existing workbooks are preserved.</p>
<select id="round"><option value="real">Release round</option><option value="mixed">Mixed-source round</option></select>
<select id="reviewer"><option value="">Choose your own identity</option><option value="sueda">Sueda Sen</option><option value="mehmet">Mehmet</option></select>
<select id="kind"><option value="entities">Entities</option><option value="relations">Relations</option></select><button id="load">Load next item</button>
<p id="progress"></p><h2 id="title"></h2><a id="source" target="_blank" rel="noopener noreferrer"></a><pre id="candidate"></pre><pre id="text"></pre>
<form id="form" hidden><label>My label <select id="label" required></select></label><label>Notes (optional)<br><textarea id="notes" rows="3" cols="65"></textarea></label>
<label><input id="confirm" type="checkbox" required> I am the selected reviewer. For this review session, I make my own source-based decisions without consulting another reviewer's decisions or the prepared labels.</label><button>Save my decision and continue</button></form><p id="message"></p>
<script>const token='TOKEN';const e=id=>document.getElementById(id);let current=null;
async function load(){e('message').textContent='';e('form').hidden=true;if(!e('reviewer').value){e('message').textContent='Choose your own identity first.';return;}
const q=new URLSearchParams({round:e('round').value,reviewer:e('reviewer').value,kind:e('kind').value});const r=await fetch('/api/item?'+q);const d=await r.json();if(!r.ok){e('message').textContent=d.error;return;}current=d;e('progress').textContent=d.completed+' / '+d.total+' decisions saved for '+d.reviewer;e('title').textContent=d.finished?'This section is complete':d.source.title;if(d.finished){e('candidate').textContent='';e('text').textContent='';e('source').textContent='';e('source').removeAttribute('href');return;}
e('candidate').textContent=d.kind==='entities'?'Entity candidate: '+d.candidate.entity_text:'Relation candidate: '+d.candidate.subject+' → '+d.candidate.object;e('text').textContent='';const t=d.source.text,c=d.candidate;if(Number.isInteger(c.start)&&Number.isInteger(c.end)){e('text').append(document.createTextNode(t.slice(0,c.start)));const m=document.createElement('mark');m.textContent=t.slice(c.start,c.end);e('text').append(m,document.createTextNode(t.slice(c.end)));}else{e('text').textContent=t;}
e('source').href=d.source.url;e('source').textContent=d.source.url;e('label').replaceChildren(new Option('Choose your label',''),...d.labels.map(x=>new Option(x,x)));e('notes').value='';e('form').hidden=false;}
e('load').onclick=load;['round','reviewer','kind'].forEach(id=>e(id).onchange=()=>{current=null;e('confirm').checked=false;e('form').hidden=true;e('progress').textContent='Load the next item for this selection.';});
e('form').onsubmit=async ev=>{ev.preventDefault();if(!current)return;const body={round:e('round').value,reviewer:e('reviewer').value,kind:e('kind').value,item_id:current.candidate.item_id,label:e('label').value,notes:e('notes').value,personal_independence_confirmation:e('confirm').checked};const r=await fetch('/api/decision',{method:'POST',headers:{'Content-Type':'application/json','X-Review-Token':token},body:JSON.stringify(body)});const d=await r.json();if(r.ok){await load();}else{e('message').textContent=d.error;}};</script></html>'''


def serve(port,root=ROOT):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,data,status=200,content_type='application/json'):
            body=data.encode() if isinstance(data,str) else json.dumps(data).encode()
            self.send_response(status);self.send_header('Content-Type',content_type+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.end_headers();self.wfile.write(body)
        def valid_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        def do_GET(self):
            if not self.valid_host():return self.send({'error':'Loopback host required'},403)
            try:
                u=urlsplit(self.path)
                if u.path=='/':return self.send(HTML.replace('TOKEN',token),content_type='text/html')
                if u.path=='/api/item':
                    q=parse_qs(u.query);return self.send(next_item(q['round'][0],q['reviewer'][0],q['kind'][0],root))
                self.send({'error':'Not found'},404)
            except (ValueError,KeyError) as exc:self.send({'error':str(exc)},400)
        def do_POST(self):
            if not self.valid_host():return self.send({'error':'Loopback host required'},403)
            try:
                if self.path!='/api/decision':return self.send({'error':'Not found'},404)
                if self.headers.get('X-Review-Token')!=token:return self.send({'error':'Invalid review token'},403)
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=20000:raise ValueError('Invalid request size')
                self.send(record(json.loads(self.rfile.read(size)),root))
            except (ValueError,KeyError) as exc:self.send({'error':str(exc)},400)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Independent source review: http://127.0.0.1:{server.server_port}',flush=True)
    server.serve_forever()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['serve','agreement']);p.add_argument('--port',type=int,default=8767);p.add_argument('--round',choices=['real','mixed'],default='real');a=p.parse_args()
    if a.action=='serve':serve(a.port)
    else:print(json.dumps(agreement(a.round),indent=2))


if __name__=='__main__':main()
