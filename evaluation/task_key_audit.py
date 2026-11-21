"""Prepare source-grounded adjudication proposals without changing human entries."""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from evaluation.real_round import ROOT, frozen_records, read_json
from evaluation.task_key_review import status, validate_record

REASONS={
 'q-pilot-github-mlops':'The frozen pilot corpus contains software releases, not dated commit-count windows and MLOps job-board observations. It cannot establish joint activity and hiring growth.',
 'q-investors-later-hiring':'The frozen pilot corpus has no funding-round and subsequent hiring-stock evidence needed to link investors to later retrieval/evaluation hiring growth.',
 'q-sector-attention':'Company release notes do not supply the required independent public-voice coverage. The shared evidence policy does not supply those missing observations.',
 'q-why-emerging':'The question asks why the emerging label applies and how it can change. The shared policy defines emerging as one independent document/operational signal. Explaining that rule is distinct from establishing a particular company\'s factual state.',
 'q-unsupported-acquisition':'No acquisition evidence is present in the frozen release corpus. Under the policy, disputed requires credible conflicting evidence; missing support alone means insufficient.',
 'q-future-performance':'The frozen sources cannot establish which company will have the highest valuation in 2027. The policy forbids converting trend scores into objective future-performance claims.',
}


def audit(directory):
    records=frozen_records(directory)
    if any(r.get('event_type')!='software_release' for r in records):
        raise ValueError('This audit applies only to the frozen release-only pilot')
    review_path=directory/'pilot-session/task-key-second-review.json'
    review=validate_record(directory,read_json(review_path))
    protocol=read_json(directory/'pilot-session/protocol.json')
    raw=read_json(directory/'pilot-session/responses.json')['responses']
    second={e['question_id']:e for e in review['entries']}
    policy=directory/'sueda-review/pilot-evidence-policy.md'
    if 'Supported by one independent document or one operational signal' not in policy.read_text():
        raise ValueError('Evidence policy changed; re-review adjudication proposals')
    proposals=[]
    for qid in protocol['task_ids']:
        entry=second[qid];initial=protocol['task_key'][qid]
        proposals.append({'question_id':qid,'initial_state':initial['expected_state'],
            'recorded_second_review_state':entry['expected_state'],
            'recorded_second_review_rationale':entry['rationale'],
            'source_based_proposed_state':initial['expected_state'],
            'source_based_reason':REASONS[qid],
            'sources':['manifest.json','records.jsonl','sueda-review/pilot-evidence-policy.md'],
            'review_issue':'The supplied rationale does not identify task-specific source support.' if entry['rationale'].strip().casefold()=='excellent' else 'Adjudicate against the cited frozen sources.',
            'measurement_limit':'A policy explanation was not collected in the categorical response form.' if qid=='q-why-emerging' else 'Any missing-evidence explanation must not be inferred from the action selection.'})
    matches={}
    for name,key in [('initial_source_key',protocol['task_key']),('recorded_second_review',second)]:
        count=sum(r['evidence_state']==key[r['question_id']]['expected_state'] for r in raw)
        matches[name]={'state_label_matches':count,'responses':len(raw),
            'match_fraction':count/len(raw) if raw else None,
            'scope':'Sensitivity to the proposed key, not final adjudicated accuracy.'}
    proposal_review=status(directory)
    # Preserve the accepted proposal's historical stage after finalization.
    proposal_review['final_adjudication_complete']=False
    return {'status':'source_based_adjudication_proposal','second_review':proposal_review,
        'source_inventory':{'records':len(records),'source_types':dict(Counter(r['source_type'] for r in records)),
            'event_types':dict(Counter(r.get('event_type') for r in records))},
        'proposals':proposals,'state_match_sensitivity':matches,
        'human_review_preserved':True,'final_adjudication_complete':False,
        'independent_entity_relation_agreement_established':False,
        'input_sha256':{str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [review_path,policy,directory/'records.jsonl',directory/'pilot-session/protocol.json',directory/'pilot-session/responses.json']}}


if __name__=='__main__':
    directory=ROOT/'evaluation/real'
    result=audit(directory)
    path=directory/'pilot-session/task-key-adjudication-proposal.json'
    path.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'status':result['status'],'review_decisions':6,
        'state_disagreements':len(result['second_review']['state_differences_from_initial_key']),
        'state_match_sensitivity':result['state_match_sensitivity']},indent=2))
