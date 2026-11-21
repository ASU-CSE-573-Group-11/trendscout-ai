"""Validate actual pilot submissions and summarize observed measurements only.

No correctness or treatment effects are inferred from task responses, consent,
or incomplete counterbalancing. Raw participant responses are never changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.pilot_session import fingerprint
from evaluation.real_round import ROOT


def statistics(rows):
    if not rows:
        return {'responses':0,'duration_seconds':None,'confidence':None}
    durations=[r['duration_seconds'] for r in rows]
    confidence=[r['confidence'] for r in rows]
    return {'responses':len(rows),'duration_seconds':{'mean':mean(durations),
        'median':median(durations),'minimum':min(durations),'maximum':max(durations)},
        'confidence':{'mean':mean(confidence),'median':median(confidence),
            'scale':'1–5','distribution':dict(sorted(Counter(confidence).items()))}}


def summarize(directory):
    session=directory/'pilot-session'
    paths={'responses':session/'responses.json','protocol':session/'protocol.json',
        'assignments':session/'assignments.json','stimuli':session/'stimuli.json',
        'manifest':session/'manifest.json','pilot':directory/'trust-pilot.json'}
    raw={name:path.read_bytes() for name,path in paths.items()}
    data={name:json.loads(value) for name,value in raw.items()}
    assignments=data['assignments']['assignments'];stimuli=data['stimuli'];protocol=data['protocol']
    for name,value in [('protocol',protocol),('assignments',assignments),('stimuli',stimuli)]:
        if fingerprint(value)!=data['manifest'][name+'_sha256']:
            raise ValueError('Frozen pilot '+name+' changed')
    lookup={(a['participant_id'],a['question_id']):a for a in assignments}
    if len(lookup)!=len(assignments):
        raise ValueError('Duplicate planned pilot task')
    participants={p['participant_id']:p for p in data['pilot']['participants']}
    responses=data['responses']['responses']
    seen=set()
    for row in responses:
        key=(row['participant_id'],row['question_id'])
        if key in seen or key not in lookup:
            raise ValueError('Duplicate or unknown submitted pilot task')
        assignment=lookup[key]
        if participants.get(key[0],{}).get('consent_confirmed') is not True:
            raise ValueError('Pilot response has no recorded consent')
        if row.get('order')!=assignment['order'] or row.get('condition')!=assignment['condition']:
            raise ValueError('Response does not match frozen assignment')
        prior={q for p,q in seen if p==key[0]}
        if assignment['order']!=len(prior)+1:
            raise ValueError('Response presentation order is incomplete')
        stimulus=stimuli[key[1]+':'+assignment['condition']]
        if row.get('stimulus_sha256')!=fingerprint(stimulus):
            raise ValueError('Submitted stimulus checksum mismatch')
        duration=row.get('duration_seconds')
        if type(duration) not in {int,float} or not math.isfinite(duration) or duration<=0:
            raise ValueError('Invalid measured pilot duration')
        if type(row.get('confidence')) is not int or not 1<=row['confidence']<=5:
            raise ValueError('Invalid participant confidence')
        if row.get('evidence_state') not in {'emerging','corroborated','disputed','stale','insufficient'} or row.get('action') not in {'answer','qualify','abstain'}:
            raise ValueError('Invalid raw participant decision')
        citations={c['number'] for c in stimulus['citations']}
        selected=row.get('evidence_numbers')
        if not isinstance(selected,list) or any(type(n) is not int or n not in citations for n in selected) or len(selected)!=len(set(selected)):
            raise ValueError('Invalid citation selection')
        if row.get('timing_method') not in {'participant_reported','server_monotonic_elapsed'}:
            raise ValueError('Unknown pilot timing method')
        seen.add(key)
    progress=[]
    for pid in sorted({a['participant_id'] for a in assignments}):
        planned=[a for a in assignments if a['participant_id']==pid]
        own=[r for r in responses if r['participant_id']==pid]
        missing=sorted([a for a in planned if (pid,a['question_id']) not in seen],key=lambda a:a['order'])
        progress.append({'participant_id':pid,'completed_tasks':len(own),'planned_tasks':len(planned),
            'remaining_tasks':len(missing),'next_task_order':missing[0]['order'] if missing else None,
            'observed_conditions':dict(Counter(r['condition'] for r in own)),
            'measurements':statistics(own)})
    complete=len(responses)==len(assignments)
    paired=None
    conditions=protocol['conditions']
    if complete and len(conditions)==2:
        pairs=[]
        for p in progress:
            own=[r for r in responses if r['participant_id']==p['participant_id']]
            groups=[[r for r in own if r['condition']==c] for c in conditions]
            if any(len(group)!=3 for group in groups):
                raise ValueError('Completed pilot must have three tasks per condition')
            pairs.append({'participant_id':p['participant_id'],
                'duration_mean_seconds':{c:mean(r['duration_seconds'] for r in group) for c,group in zip(conditions,groups)},
                'confidence_mean':{c:mean(r['confidence'] for r in group) for c,group in zip(conditions,groups)},
                'duration_difference_seconds':mean(r['duration_seconds'] for r in groups[1])-mean(r['duration_seconds'] for r in groups[0]),
                'confidence_difference':mean(r['confidence'] for r in groups[1])-mean(r['confidence'] for r in groups[0])})
        paired={'participants':len(pairs),'contrast':conditions[1]+' minus '+conditions[0],
            'per_participant':pairs,
            'mean_duration_difference_seconds':mean(p['duration_difference_seconds'] for p in pairs),
            'median_duration_difference_seconds':median(p['duration_difference_seconds'] for p in pairs),
            'mean_confidence_difference':mean(p['confidence_difference'] for p in pairs),
            'interpretation':'Observed within-participant differences only. Different task sets, shared state language and five participants do not establish a causal treatment effect.'}
    scored=data['pilot'].get('task_results',[])
    grading_methods=dict(Counter(r.get('grading_method','unspecified') for r in scored))
    grading_status='source_review_scores_require_adjudication' if scored else 'no_scores_recorded'
    finalized=None
    if (session/'task-key-adjudication.json').exists():
        from evaluation.finalize_pilot import verify as verify_final_grading
        finalized=verify_final_grading(directory)
        grading_status='complete_for_observed_fields'
    return {'status':('collection_complete_graded_observed_fields' if finalized else ('collection_complete_with_source_scores' if scored else 'collection_complete_ungraded')) if complete else 'collection_in_progress',
        'collection_complete':complete,
        'planned_tasks':len(assignments),'submitted_tasks':len(responses),
        'remaining_tasks':len(assignments)-len(responses),
        'participants_with_responses':len({r['participant_id'] for r in responses}),
        'participants_complete':sum(p['remaining_tasks']==0 for p in progress),
        'participants':progress,'observed_measurements':statistics(responses),
        'by_condition':{condition:statistics([r for r in responses if r['condition']==condition]) for condition in protocol['conditions']},
        'timing_methods':dict(Counter(r['timing_method'] for r in responses)),
        'last_recorded_at':max((r['recorded_at'] for r in responses),default=None),
        'task_key_review_method':data['pilot']['protocol']['task_key_review_method'],
        'scored_task_results':len(scored),'grading_status':grading_status,
        'recorded_grading_methods':grading_methods,
        'independent_task_key_adjudication_confirmed':False,
        'task_key_adjudication_complete':bool(finalized),
        'final_grading':finalized,
        'accuracy':finalized['metrics'] if finalized else None,
        'pilot_effect_estimate':None,'descriptive_only':True,
        'paired_condition_descriptives':paired,
        'limits':['Observed task responses are not pooled votes on one common question.',
            'Elapsed times include interruptions; they do not establish active attention.',
            'Condition summaries and paired descriptive differences do not establish a causal treatment effect.',
            'Free-text explanations were not collected. Rubric criteria requiring an explanation cannot be inferred from the action selector.',
            'Final state accuracy concerns participant judgments; unmeasured criteria and causal pilot effects are not inferred.'],
        'input_sha256':{name:hashlib.sha256(content).hexdigest() for name,content in raw.items()}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'evaluation/real')
    args=parser.parse_args()
    summary=summarize(args.directory)
    (args.directory/'pilot-session/response-summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'submitted':summary['submitted_tasks'],'planned':summary['planned_tasks'],
        'remaining':summary['remaining_tasks'],'measurements':summary['observed_measurements']},indent=2))
