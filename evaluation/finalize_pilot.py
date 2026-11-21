"""Finalize the accepted source-based key and grade only observed pilot fields.

Original participant submissions and the blind second review remain unchanged.
Uncollected explanations receive null assessments, never invented booleans.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from collectors.records import utc_now
from evaluation.real_round import ROOT, read_json, frozen_records
from evaluation.task_key_audit import audit

METHOD='team_source_assisted_adjudication_after_blind_second_review'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(rows,field):
    observed=[r[field] for r in rows if type(r.get(field)) is bool]
    return {'correct':sum(observed),'assessed':len(observed),
        'not_assessed':len(rows)-len(observed),
        'accuracy':sum(observed)/len(observed) if observed else None}


def grade_response(response,key):
    behavior=key['accepted_behaviors'];action=response['action']
    if action=='abstain':
        abstention='abstain' in behavior
    elif action=='answer':
        abstention=None if 'explain_policy_with_missing_company_specific_evidence' in behavior else False
    else:
        abstention=None if any(b in behavior for b in ['qualify_with_missing_evidence','explain_policy_with_missing_company_specific_evidence']) else False
    return {**{k:response[k] for k in ['participant_id','question_id','condition','order','duration_seconds','confidence']},
        'reported_state':response['evidence_state'],'expected_state':key['expected_state'],
        'status_correct':response['evidence_state']==key['expected_state'],
        'evidence_correct':None,'abstention_correct':abstention,
        'evidence_assessment':'not_measured: required free-text explanation was not collected',
        'abstention_assessment':'assessed from the recorded action' if abstention is not None else 'not_measured: qualifying/policy explanation was not collected',
        'grading_method':'adjudicated_key_observed_fields_only'}


def summarize_scores(rows):
    fields=['status_correct','evidence_correct','abstention_correct']
    return {field:metric(rows,field) for field in fields}


def finalize(directory):
    session=directory/'pilot-session'
    if (session/'task-key-adjudication.json').exists():
        return verify(directory)
    source_audit=audit(directory)
    proposal_path=session/'task-key-adjudication-proposal.json'
    if read_json(proposal_path)!=source_audit:
        raise ValueError('Refresh the source-based proposal before finalizing')
    raw_path=session/'responses.json';raw_digest=sha(raw_path)
    responses=read_json(raw_path)['responses']
    if len(responses)!=30:
        raise ValueError('Complete pilot collection required')
    protocol=read_json(session/'protocol.json')
    reviewed={p['question_id']:p for p in source_audit['proposals']}
    keys={qid:{**protocol['task_key'][qid],
        'expected_state':reviewed[qid]['source_based_proposed_state'],
        'adjudication_reason':reviewed[qid]['source_based_reason']} for qid in protocol['task_ids']}
    adjudication={'status':'adjudicated','method':METHOD,
        'adjudicator':'Project team (session-confirmed, source-assisted resolution)',
        'decision_source':'Project session accepted the presented source-based resolution and requested finalization.',
        'adjudicated_at':utc_now(),'task_key':keys,
        'original_rubric_preserved':True,
        'second_review_preserved':True,'state_disagreements_resolved':6,
        'external_independent_assessor':False,
        'scope':'Six frozen pilot tasks only; does not attest entity/relation annotation agreement.',
        'input_sha256':{**source_audit['input_sha256'],
            'pilot-session/task-key-adjudication-proposal.json':sha(proposal_path)}}
    scores=[grade_response(r,keys[r['question_id']]) for r in responses]
    results={'status':'finalized_for_observed_fields','method':METHOD,
        'responses':len(scores),'task_results':scores,'metrics':summarize_scores(scores),
        'by_condition':{condition:summarize_scores([r for r in scores if r['condition']==condition]) for condition in protocol['conditions']},
        'by_participant':{pid:summarize_scores([r for r in scores if r['participant_id']==pid]) for pid in sorted({r['participant_id'] for r in scores})},
        'full_protocol_measurement_complete':False,
        'limitations':['Evidence explanations and qualifying/policy rationales were not collected; corresponding assessments are null.',
            'State correctness is an exact match to the team-adjudicated key, not overall system accuracy.',
            'The second reviewer participated in the pilot; adjudication was source-assisted, not external.',
            'No causal pilot benefit is established; no entity/relation agreement is inferred.'],
        'raw_responses_sha256':raw_digest}
    pilot_path=directory/'trust-pilot.json';pilot=read_json(pilot_path)
    backup=session/'before-final-adjudication-pilot.json'
    with backup.open('xb') as handle:
        handle.write(pilot_path.read_bytes())
    for name,value in [('task-key-adjudication.json',adjudication),('final-grading.json',results)]:
        with (session/name).open('x',encoding='utf-8') as handle:
            handle.write(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    pilot.update(status='complete',adjudication_status='team_source_assisted_adjudicated',
        grading_status='complete_for_observed_fields',task_results=scores,
        task_key_adjudication_file='pilot-session/task-key-adjudication.json',
        final_grading_file='pilot-session/final-grading.json',
        full_protocol_measurement_complete=False)
    pilot['protocol']['task_key_review_method']=METHOD
    pilot_path.write_text(json.dumps(pilot,indent=2,ensure_ascii=False)+'\n')
    if sha(raw_path)!=raw_digest:
        raise ValueError('Raw participant responses changed during finalization')
    return verify(directory)


def verify(directory):
    frozen_records(directory)
    session=directory/'pilot-session'
    adjudication=read_json(session/'task-key-adjudication.json')
    if adjudication.get('method')!=METHOD or adjudication.get('status')!='adjudicated':
        raise ValueError('Unknown adjudication method or status')
    for relative,digest in adjudication['input_sha256'].items():
        if sha(directory/relative)!=digest:
            raise ValueError('Adjudication input checksum mismatch')
    protocol=read_json(session/'protocol.json')
    source_audit=read_json(session/'task-key-adjudication-proposal.json')
    proposals={p['question_id']:p for p in source_audit['proposals']}
    keys=adjudication['task_key']
    if set(keys)!=set(protocol['task_ids']):
        raise ValueError('Incomplete final task key')
    for qid,key in keys.items():
        expected={**protocol['task_key'][qid],
            'expected_state':proposals[qid]['source_based_proposed_state'],
            'adjudication_reason':proposals[qid]['source_based_reason']}
        if key!=expected:
            raise ValueError('Adjudicated key differs from accepted source proposal')
    result=read_json(session/'final-grading.json')
    raw=[*read_json(session/'responses.json')['responses']]
    computed=[grade_response(r,keys[r['question_id']]) for r in raw]
    if result['task_results']!=computed or result['metrics']!=summarize_scores(computed) or result['raw_responses_sha256']!=sha(session/'responses.json'):
        raise ValueError('Final grades differ from recorded responses and key')
    expected_conditions={c:summarize_scores([r for r in computed if r['condition']==c]) for c in protocol['conditions']}
    expected_participants={p:summarize_scores([r for r in computed if r['participant_id']==p]) for p in sorted({r['participant_id'] for r in computed})}
    if result['by_condition']!=expected_conditions or result['by_participant']!=expected_participants:
        raise ValueError('Final score breakdown mismatch')
    pilot=read_json(directory/'trust-pilot.json')
    matches=(pilot['task_results']==computed and pilot['protocol']['task_key_review_method']==METHOD
        and pilot.get('adjudication_status')=='team_source_assisted_adjudicated')
    return {'status':'finalized_for_observed_fields','adjudication_complete':True,
        'adjudication_method':METHOD,'responses':len(computed),'metrics':result['metrics'],
        'full_protocol_measurement_complete':False,'external_independent_assessor':False,
        'legacy_pilot_container_matches_final_grading':matches}


def synchronize(directory):
    """Keep the legacy container aligned without modifying raw submissions."""
    verify(directory)
    session=directory/'pilot-session';path=directory/'trust-pilot.json'
    pilot=read_json(path);final=read_json(session/'final-grading.json')
    if pilot['task_results']!=final['task_results']:
        backup=session/('legacy-source-grading-'+sha(path)[:12]+'.json')
        if not backup.exists():backup.write_bytes(path.read_bytes())
    pilot.update(status='complete',adjudication_status='team_source_assisted_adjudicated',
        grading_status='complete_for_observed_fields',task_results=final['task_results'],
        task_key_adjudication_file='pilot-session/task-key-adjudication.json',
        final_grading_file='pilot-session/final-grading.json',full_protocol_measurement_complete=False)
    pilot['protocol']['task_key_review_method']=METHOD
    path.write_text(json.dumps(pilot,indent=2,ensure_ascii=False)+'\n')
    return verify(directory)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['finalize','verify','synchronize'])
    parser.add_argument('--directory',type=Path,default=ROOT/'evaluation/real')
    args=parser.parse_args()
    print(json.dumps({'finalize':finalize,'verify':verify,'synchronize':synchronize}[args.action](args.directory),indent=2))
