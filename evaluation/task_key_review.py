"""Collect an actual second task-key review without displaying the initial key.

This review is separate from participant responses, entity/relation annotation,
and final adjudication. No reviewer decisions are supplied by this program.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote

from collectors.records import utc_now
from evaluation.pilot_analysis import summarize
from evaluation.pilot_console import page, esc, options, frozen_session
from evaluation.real_round import ROOT, frozen_records, read_json

REVIEWERS=['Sueda Sen','Mehmet Aksit','Vidya Sagar Dudekula','Faisal Barkat Khorasi']
STATES=['emerging','corroborated','disputed','stale','insufficient']
ACTIONS=['answer','qualify','abstain']


def inputs(directory):
    frozen_session(directory)
    frozen_records(directory)
    if not summarize(directory)['collection_complete']:
        raise ValueError('Complete participant collection before revealing review materials')
    session=directory/'pilot-session'
    paths={'protocol':session/'protocol.json','stimuli':session/'stimuli.json',
        'corpus_manifest':directory/'manifest.json','responses':session/'responses.json',
        'policy':directory/'sueda-review/pilot-evidence-policy.md'}
    return {name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in paths.items()}


def validate_record(directory,record):
    protocol=read_json(directory/'pilot-session/protocol.json')
    if record.get('status')!='blind_second_review_complete' or record.get('method')!='personal_source_review':
        raise ValueError('Completed personal source-review record required')
    current=inputs(directory)
    recorded=record.get('input_sha256',{})
    if recorded!=current:
        # A downstream grading-status update is not a new participant answer.
        # Retain the exact reviewed snapshot and verify every other field.
        snapshot=directory/'pilot-session/reviewed-responses.snapshot.json'
        compatible=(snapshot.exists() and
            hashlib.sha256(snapshot.read_bytes()).hexdigest()==recorded.get('responses') and
            {k:v for k,v in recorded.items() if k!='responses'}=={k:v for k,v in current.items() if k!='responses'})
        if compatible:
            old=read_json(snapshot);new=read_json(directory/'pilot-session/responses.json')
            clean=lambda value:{**value,'responses':[{k:v for k,v in row.items() if k!='grading_status'} for row in value['responses']]}
            compatible=clean(old)==clean(new)
        if not compatible:
            raise ValueError('Review source fingerprints changed')
    if record.get('reviewer') not in REVIEWERS or record.get('personal_independent_review_confirmed') is not True:
        raise ValueError('Named personal review confirmation required')
    entries=record.get('entries',[])
    if len(entries)!=6 or {e['question_id'] for e in entries}!=set(protocol['task_ids']):
        raise ValueError('Six distinct task-key decisions required')
    for entry in entries:
        if entry.get('expected_state') not in STATES or not isinstance(entry.get('rationale'),str) or not entry['rationale'].strip():
            raise ValueError('A state and source rationale are required for every task')
        actions=entry.get('accepted_actions')
        if not isinstance(actions,list) or not actions or len(actions)!=len(set(actions)) or not set(actions)<=set(ACTIONS):
            raise ValueError('Select at least one distinct accepted action per task')
        if entry.get('source_basis') not in {'frozen_corpus','evidence_policy','corpus_and_policy'}:
            raise ValueError('Source basis required')
    return record


def record_review(directory,reviewer,entries,confirmed,expected_inputs):
    record={'status':'blind_second_review_complete','method':'personal_source_review',
        'reviewer':reviewer,'completed_at':utc_now(),'entries':entries,
        'personal_independent_review_confirmed':confirmed,'input_sha256':expected_inputs,
        'reviewer_was_pilot_participant':True,
        'independence_scope':'Reviewer confirms decisions were entered without consulting the initial task key or other participant responses. The reviewer is a study participant, not an external assessor.',
        'scope':'Second task-key decisions only. Does not attest entity/relation annotation or final adjudication.'}
    validate_record(directory,record)
    target=directory/'pilot-session/task-key-second-review.json'
    with target.open('x',encoding='utf-8') as handle:
        handle.write(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
    return status(directory)


def status(directory):
    target=directory/'pilot-session/task-key-second-review.json'
    if not target.exists():
        return {'status':'review_interface_available','recorded_decisions':0,'final_adjudication_complete':False}
    record=validate_record(directory,read_json(target))
    initial=read_json(directory/'pilot-session/protocol.json')['task_key']
    differences=[{'question_id':e['question_id'],'initial_state':initial[e['question_id']]['expected_state'],
                  'second_state':e['expected_state']} for e in record['entries']
                 if initial[e['question_id']]['expected_state']!=e['expected_state']]
    adjudicated=False
    if (directory/'pilot-session/task-key-adjudication.json').exists():
        from evaluation.finalize_pilot import verify as verify_final_grading
        adjudicated=verify_final_grading(directory)['adjudication_complete']
    return {'status':record['status'],'reviewer':record['reviewer'],'recorded_decisions':6,
        'state_differences_from_initial_key':differences,'final_adjudication_complete':adjudicated,
        'scope':'Compare and adjudicate before final grading; this is not entity/relation agreement.'}


class ReviewConsole:
    def __init__(self,directory):
        self.directory=directory
        self.fingerprints=inputs(directory)
        self.token=secrets.token_urlsafe(32)
        self.records={r['record_id']:r for r in frozen_records(directory)}
        self.protocol=read_json(directory/'pilot-session/protocol.json')
        self.stimuli=read_json(directory/'pilot-session/stimuli.json')

    def home(self):
        if (self.directory/'pilot-session/task-key-second-review.json').exists():
            return page('<h1>Second review recorded</h1><p>The six source-review decisions are saved. Adjudication and final grading are separate. Existing decisions cannot be overwritten from this form.</p>')
        body='<h1>Second task-key source review</h1><p>Review the six questions against the frozen release corpus and the shared evidence policy. The initial task key and participant responses are hidden. Supplementary hiring, funding and public-voice datasets are outside this pilot snapshot.</p><p>Choose your own name and enter your own decisions. All listed team reviewers participated in the pilot, so this is not an external-assessor review.</p><p><a href="/policy" target="_blank">Read the shared evidence policy</a></p><details><summary>Browse all 45 frozen source documents</summary><ul>'
        body+=''.join('<li><a target="_blank" href="/source/'+esc(r['record_id'])+'">'+esc(r['title'])+'</a></li>' for r in self.records.values())
        body+='</ul></details><form method="post" action="/review"><input type="hidden" name="token" value="'+esc(self.token)+'"><label>Your name '+options('reviewer',REVIEWERS)+'</label>'
        for index,qid in enumerate(self.protocol['task_ids'],1):
            stimulus=self.stimuli[qid+':'+self.protocol['conditions'][0]]
            body+='<fieldset><legend>Question '+str(index)+' of 6</legend><p>'+esc(stimulus['question'])+'</p><details><summary>Displayed source passages</summary>'
            for c in stimulus['citations']:
                body+='<article><h3>['+str(c['number'])+'] '+esc(c['title'])+'</h3><p>'+esc(c['source_url'])+'</p><pre>'+esc(c['text'])+'</pre></article>'
            body+='</details><label>Correct evidence state '+options('state_'+qid,STATES)+'</label><p>Accepted answer actions (select all that apply)</p>'
            body+=''.join('<label><input type="checkbox" name="actions_'+esc(qid)+'" value="'+a+'"> '+a+'</label>' for a in ACTIONS)
            body+='<label>Source basis '+options('basis_'+qid,['frozen_corpus','evidence_policy','corpus_and_policy'])+'</label><label>Explain the source basis for your decision<br><textarea required rows="4" cols="80" name="reason_'+esc(qid)+'"></textarea></label></fieldset>'
        body+='<label><input required type="checkbox" name="confirmed" value="yes"> I personally checked the sources and entered these decisions without consulting the initial task key or other participants’ responses.</label><button type="submit">Save my six review decisions</button></form>'
        return page(body)


def make_handler(console):
    class Handler(BaseHTTPRequestHandler):
        def send_page(self,text,code=200):
            body=text.encode('utf-8');self.send_response(code)
            for name,value in [('Content-Type','text/html; charset=utf-8'),('Content-Length',str(len(body))),
                ('Cache-Control','no-store'),('X-Frame-Options','DENY'),
                ('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")]:self.send_header(name,value)
            self.end_headers();self.wfile.write(body)

        def do_GET(self):
            if self.path=='/':self.send_page(console.home());return
            if self.path=='/policy':
                text=(console.directory/'sueda-review/pilot-evidence-policy.md').read_text()
                self.send_page(page('<h1>Shared evidence policy</h1><pre>'+esc(text)+'</pre>'));return
            if self.path.startswith('/source/'):
                record=console.records.get(unquote(self.path[len('/source/'):]))
                if record:
                    self.send_page(page('<h1>'+esc(record['title'])+'</h1><p>'+esc(record['source_url'])+'</p><pre>'+esc(record['text'])+'</pre>'));return
            self.send_page(page('<h1>Not found</h1>'),404)

        def do_POST(self):
            try:
                host=self.headers.get('Host','');origin=self.headers.get('Origin')
                if host not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'} or (origin and urlsplit(origin).netloc!=host):
                    raise ValueError('Use the local review page')
                if self.path!='/review':raise ValueError('Unknown review action')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=100000:raise ValueError('Invalid review size')
                values=parse_qs(self.rfile.read(length).decode('utf-8'),keep_blank_values=True)
                if values.get('token')!=[console.token]:raise ValueError('Open the review page before submitting')
                entries=[{'question_id':qid,'expected_state':values['state_'+qid][0],
                    'accepted_actions':values.get('actions_'+qid,[]),'source_basis':values['basis_'+qid][0],
                    'rationale':values['reason_'+qid][0]} for qid in console.protocol['task_ids']]
                record_review(console.directory,values['reviewer'][0],entries,values.get('confirmed')==['yes'],console.fingerprints)
                self.send_page(page('<h1>Six review decisions saved</h1><p>Your second source review is recorded. The original participant responses are unchanged. Adjudication and final grading can now use this review.</p>'))
            except (ValueError,KeyError,IndexError,FileExistsError) as exc:
                self.send_page(page('<h1>Review not saved</h1><p>'+esc(exc)+'</p><p>Use Back to correct the form. No decisions are preselected.</p>'),400)

        def log_message(self,*args):pass
    return Handler


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['serve','status'])
    parser.add_argument('--directory',type=Path,default=ROOT/'evaluation/real')
    parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args()
    if args.action=='status':print(json.dumps(status(args.directory),indent=2))
    else:
        server=HTTPServer(('127.0.0.1',args.port),make_handler(ReviewConsole(args.directory)))
        print(f'Second task-key review: http://127.0.0.1:{args.port}/',flush=True)
        server.serve_forever()
