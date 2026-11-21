"""Local English pilot console: actual participant submissions and elapsed time.

Serves only on loopback. Never creates expected answers, correctness grades,
participant identities, or consent. Uses the existing frozen task assignments.
"""
from __future__ import annotations

import argparse
import html
import json
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.pilot_session import fingerprint, record_response
from evaluation.real_round import ROOT, read_json


def esc(value):
    return html.escape(str(value),quote=True)


def frozen_session(directory):
    session=directory/'pilot-session'
    manifest=read_json(session/'manifest.json')
    values={k:read_json(session/name) for k,name in
        [('protocol','protocol.json'),('assignments','assignments.json'),('stimuli','stimuli.json')]}
    assignments=values['assignments']['assignments']
    for key,value in [('protocol',values['protocol']),('assignments',assignments),('stimuli',values['stimuli'])]:
        if fingerprint(value)!=manifest[key+'_sha256']:
            raise ValueError('Frozen pilot inputs changed')
    return assignments,values['stimuli']


class PilotConsole:
    def __init__(self,directory,clock=time.monotonic):
        self.directory=directory
        self.clock=clock
        self.sessions={}
        self.start_token=secrets.token_urlsafe(32)
        frozen_session(directory)

    def start(self,pid):
        assignments,stimuli=frozen_session(self.directory)
        participants={p['participant_id']:p for p in read_json(self.directory/'trust-pilot.json')['participants']}
        if participants.get(pid,{}).get('consent_confirmed') is not True:
            raise ValueError('Recorded participant consent is required')
        existing=read_json(self.directory/'pilot-session/responses.json')['responses']
        if any(s['assignment']['participant_id']==pid for s in self.sessions.values()):
            raise ValueError('This participant already has an open task. Return to that task tab.')
        completed=[r for r in existing if r['participant_id']==pid]
        planned=sorted([a for a in assignments if a['participant_id']==pid],key=lambda a:a['order'])
        if len(completed)>=len(planned):
            raise ValueError('All assigned tasks have already been submitted')
        assignment=planned[len(completed)]
        token=secrets.token_urlsafe(32)
        stimulus=stimuli[assignment['question_id']+':'+assignment['condition']]
        self.sessions[token]={'assignment':assignment,'started':self.clock(),'stimulus':stimulus}
        return token,assignment,stimulus

    def submit(self,token,values):
        if token not in self.sessions:
            raise ValueError('Unknown or already submitted task session')
        session=self.sessions[token]
        assignment=session['assignment']
        elapsed=self.clock()-session['started']
        response={'participant_id':assignment['participant_id'],'question_id':assignment['question_id'],
            'evidence_state':values['evidence_state'],'evidence_numbers':values['evidence_numbers'],
            'action':values['action'],'confidence':values['confidence'],
            'duration_seconds':elapsed}
        result=record_response(self.directory,response,timing_method='server_monotonic_elapsed')
        del self.sessions[token]
        return result


STYLE='''body{font:16px system-ui,sans-serif;color:#17212b;background:#f5f7fa;margin:0}main{max-width:960px;margin:32px auto;padding:28px;background:white;border:1px solid #dce2e8;border-radius:12px}h1{font-size:28px}h2{font-size:21px;margin-top:30px}p,pre{line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}label{display:block;margin:12px 0}select,button{font:inherit;padding:10px;border:1px solid #8996a4;border-radius:6px}button{background:#184f83;color:white;cursor:pointer}fieldset{margin:20px 0;border:1px solid #ccd5df;padding:16px}a{color:#18568c;overflow-wrap:anywhere}.note{color:#526273}article{border-top:1px solid #dde3e9;margin-top:18px;padding-top:12px}'''


def page(body):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TrendScout pilot</title><style>'+STYLE+'</style><main>'+body+'</main></html>'


def options(name,choices):
    return '<select required name="'+name+'"><option value="">Choose your response</option>'+''.join('<option value="'+esc(c)+'">'+esc(c)+'</option>' for c in choices)+'</select>'


def task_page(token,assignment,stimulus):
    content=f"<h1>{esc(assignment['participant_id'])}: task {assignment['order']} of 6</h1><p class='note'>Timing has started. Read independently and submit your own answer. Elapsed time includes interruptions. Do not inspect another participant's responses or the task key.</p><h2>Question</h2><p>{esc(stimulus['question'])}</p><h2>System answer</h2><pre>{esc(stimulus['answer_text'])}</pre>"
    if 'overall_state' in stimulus:
        content+='<h2>Displayed evidence state</h2><p>'+esc(stimulus['overall_state'])+'</p>'
        for path in stimulus.get('graph_paths',[]):
            content+='<pre>'+esc('\n'.join(str(s.get('from'))+' → '+str(s.get('type'))+' → '+str(s.get('to')) for s in path.get('steps',[])))+'</pre>'
        content+='<pre>'+esc(json.dumps(stimulus.get('evidence_states',[]),ensure_ascii=False,indent=2))+'</pre>'
    content+='<h2>Citations</h2>'
    for c in stimulus['citations']:
        content+=f"<article><h3>[{c['number']}] {esc(c['title'])}</h3><p>{esc(c['source_url'])}</p><pre>{esc(c['text'])}</pre></article>"
    content+='<h2>Your response</h2><form method="post" action="/submit"><input type="hidden" name="token" value="'+esc(token)+'">'
    content+='<label>Evidence state '+options('evidence_state',['emerging','corroborated','disputed','stale','insufficient'])+'</label>'
    content+='<fieldset><legend>Supporting citation numbers</legend><p>Select only sources you used. Leave empty when none supports the answer.</p>'
    for c in stimulus['citations']:
        content+=f'<label><input type="checkbox" name="evidence_numbers" value="{c["number"]}"> [{c["number"]}] {esc(c["title"])}</label>'
    content+='</fieldset><label>Action '+options('action',['answer','qualify','abstain'])+'</label><label>Confidence (1 = lowest, 5 = highest) '+options('confidence',['1','2','3','4','5'])+'</label><button type="submit">Submit my response</button></form>'
    return page(content)


def progress(console):
    assignments=read_json(console.directory/'pilot-session/assignments.json')['assignments']
    responses=read_json(console.directory/'pilot-session/responses.json')['responses']
    return [{'participant_id':pid,
        'completed':sum(r['participant_id']==pid for r in responses),
        'planned':sum(a['participant_id']==pid for a in assignments)}
        for pid in sorted({a['participant_id'] for a in assignments})]


def receipt_page(console,pid):
    own=next(p for p in progress(console) if p['participant_id']==pid)
    remaining=own['planned']-own['completed']
    body='<h1>'+esc(pid)+': '+str(own['completed'])+' of '+str(own['planned'])+' tasks saved</h1>'
    body+='<p>Your response and measured elapsed time were saved. Correctness is graded separately.</p>'
    if remaining:
        body+='<p><strong>'+str(remaining)+' tasks remain for you. The pilot requires all six tasks per participant.</strong></p>'
        body+='<form method="post" action="/start"><input type="hidden" name="start_token" value="'+esc(console.start_token)+'"><input type="hidden" name="participant_id" value="'+esc(pid)+'"><button type="submit">Start my next task</button></form>'
    else:
        body+='<p>You have completed all your assigned tasks. Thank you.</p>'
    return page(body+'<p><a href="/">Return to participant selection</a></p>')


def make_handler(console):
    class Handler(BaseHTTPRequestHandler):
        def send_page(self,body,status=200):
            payload=body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(payload)

        def do_GET(self):
            if self.path!='/':
                self.send_page(page('<h1>Not found</h1>'),404);return
            participants=read_json(console.directory/'trust-pilot.json')['participants']
            status=''.join('<li>'+esc(p['participant_id'])+': '+str(p['completed'])+'/'+str(p['planned'])+' tasks saved</li>' for p in progress(console))
            body='<h1>TrendScout participant pilot</h1><p><strong>Each person completes six tasks independently.</strong> One submitted task is not the complete pilot.</p><ul>'+status+'</ul><p>Use your assigned participant ID. This screen records actual responses and elapsed time; no answer is preselected.</p><form method="post" action="/start"><input type="hidden" name="start_token" value="'+esc(console.start_token)+'"><label>Your participant ID '+options('participant_id',[p['participant_id'] for p in participants if p.get('consent_confirmed') is True])+'</label><button type="submit">Start my next task</button></form>'
            self.send_page(page(body))

        def do_POST(self):
            try:
                expected_hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
                host=self.headers.get('Host','')
                origin=self.headers.get('Origin')
                if host not in expected_hosts or (origin and urlsplit(origin).netloc!=host):
                    raise ValueError('Use the local pilot page to submit')
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16000:
                    raise ValueError('Invalid response size')
                values=parse_qs(self.rfile.read(size).decode('utf-8'),keep_blank_values=True)
                if self.path=='/start':
                    if values.get('start_token')!=[console.start_token]:
                        raise ValueError('Open the local pilot page before starting')
                    token,assignment,stimulus=console.start(values['participant_id'][0])
                    self.send_page(task_page(token,assignment,stimulus));return
                if self.path=='/submit':
                    result=console.submit(values['token'][0],{'evidence_state':values['evidence_state'][0],
                        'evidence_numbers':[int(n) for n in values.get('evidence_numbers',[])],
                        'action':values['action'][0],'confidence':int(values['confidence'][0])})
                    self.send_page(receipt_page(console,result['participant_id']));return
                self.send_page(page('<h1>Not found</h1>'),404)
            except (ValueError,KeyError,IndexError) as exc:
                self.send_page(page('<h1>Response not recorded</h1><p>'+esc(exc)+'</p><p>Use Back to correct the form. The elapsed timer continues.</p>'),400)

        def log_message(self,*args):
            pass
    return Handler


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'evaluation/real')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    console=PilotConsole(args.directory)
    server=HTTPServer(('127.0.0.1',args.port),make_handler(console))
    print(f'Participant console: http://127.0.0.1:{args.port}/',flush=True)
    server.serve_forever()
