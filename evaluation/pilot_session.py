"""Prepare counterbalanced pilot assignments and retain actual response records.

Randomness assigns conditions and task order only. It never creates a person,
consent, a response, a correctness value, or a response duration.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import random
from pathlib import Path

from collectors.records import utc_now
from evaluation.real_round import ROOT, read_json, write_json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def prepare(directory, count=5, seed=20261121):
    if not 5 <= count <= 8:
        raise ValueError('pilot requires 5-8 planned participants')
    out=directory/'pilot-session'
    if out.exists():
        raise ValueError('refusing to overwrite frozen pilot session')
    pilot=read_json(directory/'trust-pilot.json')
    protocol=pilot['protocol']
    task_ids=protocol['task_ids']
    answers_path=directory/'answers/hybrid.jsonl.gz'
    bundles={b['question_id']:b for b in map(json.loads,gzip.decompress(answers_path.read_bytes()).decode().splitlines())}
    if len(task_ids)!=6 or len(set(task_ids))!=6 or not set(task_ids)<=set(bundles):
        raise ValueError('six unique tasks and saved answer stimuli required')
    rng=random.Random(seed)
    orders=[protocol['conditions'][i%2] for i in range(count)]
    rng.shuffle(orders)
    assignments=[]
    stimuli={}
    for index,first in enumerate(orders,1):
        tasks=list(task_ids);rng.shuffle(tasks)
        second=next(c for c in protocol['conditions'] if c!=first)
        for order,qid in enumerate(tasks,1):
            condition=first if order<=3 else second
            assignments.append({'participant_id':f'P{index:02d}','question_id':qid,'order':order,'condition':condition})
            key=qid+':'+condition
            bundle=bundles[qid]
            view={'question_id':qid,'question':bundle['question'],'answer_text':bundle['answer_text'],
                  'citations':[{'number':c['number'],'title':c.get('title'),'source_url':c.get('source_url'),
                                'text':(c.get('text') or '')[:400]} for c in bundle['citations']]}
            if condition=='citations_plus_state_and_path':
                view.update(overall_state=bundle['overall_state'],graph_paths=bundle['graph_paths'],
                            evidence_states=[{'text':c['text'],'state':c['evidence_state'],'reason':c.get('evidence_reason')}
                                             for c in bundle['claims']])
            stimuli[key]=view
    out.mkdir()
    write_json(out/'protocol.json',copy.deepcopy(protocol))
    write_json(out/'assignments.json',{'status':'planned_assignments','seed':seed,'assignments':assignments})
    write_json(out/'stimuli.json',stimuli)
    write_json(out/'responses.json',{'responses':[]})
    write_json(out/'manifest.json',{'prepared_at':utc_now(),'protocol_sha256':fingerprint(protocol),
        'answers_sha256':hashlib.sha256(answers_path.read_bytes()).hexdigest(),
        'assignments_sha256':fingerprint(assignments),'stimuli_sha256':fingerprint(stimuli),
        'participants_planned':count,'randomization_scope':'Condition blocks and task order only.'})
    return {'status':'pilot_session_prepared','planned':count,'tasks':len(assignments)}


def register_reported_consents(directory):
    """Record the self-consent and four-person group approval actually reported."""
    path=directory/'trust-pilot.json'
    pilot=read_json(path)
    if pilot['participants']:
        raise ValueError('participants already recorded; preserve existing consent records')
    now=utc_now()
    pilot['participants']=[{'participant_id':f'P{i:02d}','consent_confirmed':True,
        'consent_recorded_at':now,'consent_method':'group_approval_reported_by_P05',
        'consent_source':'Explicit report that all four team members approve participation in the active project session.',
        'role':'team_member'} for i in range(1,5)]
    pilot['participants'].append({'participant_id':'P05','consent_confirmed':True,
        'consent_recorded_at':now,'consent_method':'self_report_in_project_session',
        'consent_source':'Participant self-identifies and explicitly approves participation in the active session.',
        'role':'external_participant'})
    pilot['status']='consent_reports_recorded_tasks_pending'
    for slot in pilot.get('enrollment_slots',[]):
        slot['enrolled']=slot['slot_id'] in {p['participant_id'] for p in pilot['participants']}
    write_json(path,pilot)
    return {'consent_records':len(pilot['participants']),'task_results':len(pilot['task_results'])}


def record_response(directory,response, *, timing_method='participant_reported'):
    if timing_method not in {'participant_reported','server_monotonic_elapsed'}:
        raise ValueError('unsupported timing method')
    session=directory/'pilot-session'
    protocol=read_json(session/'protocol.json')
    manifest=read_json(session/'manifest.json')
    assignments=read_json(session/'assignments.json')['assignments']
    stimuli=read_json(session/'stimuli.json')
    if fingerprint(protocol)!=manifest['protocol_sha256'] or fingerprint(assignments)!=manifest['assignments_sha256'] or fingerprint(stimuli)!=manifest['stimuli_sha256']:
        raise ValueError('frozen pilot inputs changed')
    participants={p['participant_id']:p for p in read_json(directory/'trust-pilot.json')['participants']}
    pid,qid=response['participant_id'],response['question_id']
    if pid not in participants or participants[pid].get('consent_confirmed') is not True:
        raise ValueError('recorded participant consent required')
    assignment=next((a for a in assignments if a['participant_id']==pid and a['question_id']==qid),None)
    if not assignment:
        raise ValueError('unknown participant task')
    if response.get('evidence_state') not in {'emerging','corroborated','disputed','stale','insufficient'}:
        raise ValueError('evidence_state required')
    if response.get('action') not in {'answer','qualify','abstain'}:
        raise ValueError('action must be answer, qualify, or abstain')
    if type(response.get('confidence')) is not int or response['confidence'] not in range(1,6):
        raise ValueError('confidence must be an integer from 1 to 5')
    import math
    duration=response.get('duration_seconds')
    if type(duration) not in {int,float} or not math.isfinite(duration) or duration<=0:
        raise ValueError('actual positive duration_seconds required')
    valid_numbers={c['number'] for c in stimuli[qid+':'+assignment['condition']]['citations']}
    if not isinstance(response.get('evidence_numbers'),list) or any(type(n) is not int or n not in valid_numbers for n in response['evidence_numbers']) or len(response['evidence_numbers'])!=len(set(response['evidence_numbers'])):
        raise ValueError('evidence_numbers must refer to displayed citations')
    current=read_json(session/'responses.json')
    if any(r['participant_id']==pid and r['question_id']==qid for r in current['responses']):
        raise ValueError('response already recorded; refusing to overwrite')
    if assignment['order'] != 1 + sum(r['participant_id']==pid for r in current['responses']):
        raise ValueError('record tasks in the planned presentation order')
    current['responses'].append({**response,**assignment,'recorded_at':utc_now(),
        'timing_method':timing_method,'stimulus_sha256':fingerprint(stimuli[qid+':'+assignment['condition']]),
        'grading_status':'pending_task_key_adjudication'})
    write_json(session/'responses.json',current)
    return {'recorded':len(current['responses']),'participant_id':pid,'question_id':qid}


def integrate_response_results(directory):
    """Add rule-based correctness fields to the 30 already-recorded actual responses."""
    if (directory/'pilot-session/task-key-adjudication.json').exists():
        from evaluation.finalize_pilot import synchronize
        return synchronize(directory)
    session = directory/'pilot-session'
    pilot = read_json(directory/'trust-pilot.json')
    responses = read_json(session/'responses.json')['responses']
    assignments = read_json(session/'assignments.json')['assignments']
    if len(responses) != len(assignments):
        raise ValueError('all planned participant responses are required before integration')

    task_key = pilot['protocol']['task_key']
    results = []
    for response in responses:
        qid = response['question_id']
        key = task_key[qid]
        expected_state = key['expected_state']
        accepted_behaviors = set(key['accepted_behaviors'])
        action = response['action']

        if qid == 'q-why-emerging':
            status_correct = response['evidence_state'] == expected_state
            evidence_correct = status_correct and action in {'qualify', 'answer'}
            abstention_correct = action == 'abstain'
        else:
            status_correct = (
                action in accepted_behaviors
                and (response['evidence_state'] == 'insufficient'
                     or action in {'abstain', 'qualify'})
            )
            evidence_correct = bool(
                action in accepted_behaviors
                and not response['evidence_numbers']
            )
            abstention_correct = action in {'abstain', 'qualify'}

        results.append({
            'participant_id': response['participant_id'],
            'question_id': qid,
            'condition': response['condition'],
            'order': response['order'],
            'status_correct': status_correct,
            'evidence_correct': evidence_correct,
            'abstention_correct': abstention_correct,
            'duration_seconds': response['duration_seconds'],
            'confidence': response['confidence'],
            'grading_method': 'single_source_review_pending_second_review',
        })

    pilot['status'] = 'complete'
    pilot['adjudication_status'] = 'single_source_graded_pending_second_review'
    pilot['task_results'] = results
    write_json(directory/'trust-pilot.json', pilot)
    payload = read_json(session/'responses.json')
    for response in payload['responses']:
        response['grading_status'] = 'graded_single_source_pending_second_review'
    write_json(session/'responses.json', payload)
    return {'responses': len(results), 'participants': len({r['participant_id'] for r in results}),
            'status': pilot['status']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','record','integrate-results'])
    parser.add_argument('--directory',type=Path,default=ROOT/'evaluation/real')
    parser.add_argument('--response',type=Path)
    args=parser.parse_args()
    if args.action=='prepare':
        print(json.dumps(prepare(args.directory),indent=2))
    elif args.action=='integrate-results':
        print(json.dumps(integrate_response_results(args.directory),indent=2))
    else:
        if not args.response:parser.error('--response is required')
        print(json.dumps(record_response(args.directory,read_json(args.response)),indent=2))
