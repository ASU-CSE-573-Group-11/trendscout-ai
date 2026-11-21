"""Report actual study inputs without manufacturing missing participant data."""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.records import utc_now
from evaluation.real_round import ROOT, read_json, write_json


def rows(path):
    with path.open(newline='',encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def _annotation_inputs_complete(rounds):
    if not rounds:return False
    for round_info in rounds:
        if round_info['direct_review_collection'].get('status')!='complete_for_pairwise_agreement':
            return False
        for name in ['sueda','mehmet']:
            rev=round_info['reviewers'][name]
            if not rev.get('independent_human_attested'):return False
            if rev['entity_labels']!=rev['entity_candidates'] or rev['relation_labels']!=rev['relation_candidates']:
                return False
        corpus=round_info['corpus_decisions'];qrels=round_info['qrels_fields']
        docs=round_info['corpus_documents'];pairs=round_info['qrels_pairs']
        for key in ['sueda_include','mehmet_include','final_include','adjudicator']:
            if corpus.get(key,0)!=docs:return False
        for key in ['sueda_grade','mehmet_grade','final_grade','adjudicator']:
            if qrels.get(key,0)!=pairs:return False
    return True


def _remaining_actual_inputs(rounds, assignments, responses, finalized):
    remaining=[]
    if len(responses)<len(assignments):
        remaining.append(f"{len(assignments)-len(responses)} additional participant responses with measured durations and confidence")
    if not finalized:
        remaining.append('Independent task-key review and correctness grading')
    if not _annotation_inputs_complete(rounds):
        remaining.extend([
            'Independent annotation attestations and second-review labels',
            'Final corpus/relevance adjudication',
        ])
    return remaining


def report(root=ROOT):
    from evaluation.task_key_review import status as task_key_review_status
    index=read_json(root/'evaluation/study-index.json')
    pilot_dir=root/index['pilot_round']['directory']
    pilot=read_json(pilot_dir/'trust-pilot.json')
    finalized=None
    if (pilot_dir/'pilot-session/task-key-adjudication.json').exists():
        from evaluation.finalize_pilot import verify as verify_final_grading
        finalized=verify_final_grading(pilot_dir)
    session=root/index['pilot_round']['session']
    assignments=read_json(session/'assignments.json')['assignments']
    responses=read_json(session/'responses.json')['responses']
    by_participant=[]
    for pid in sorted({a['participant_id'] for a in assignments}):
        planned=[a for a in assignments if a['participant_id']==pid]
        supplied=[r for r in responses if r['participant_id']==pid]
        by_participant.append({'participant_id':pid,'planned_tasks':len(planned),
            'submitted_responses':len(supplied),
            'missing_question_ids':[a['question_id'] for a in planned if not any(r['question_id']==a['question_id'] for r in supplied)]})
    key=pilot['protocol']['task_key']
    content_complete=set(key)==set(pilot['protocol']['task_ids']) and all(
        k.get('expected_state') in {'emerging','corroborated','disputed','stale','insufficient'}
        and k.get('accepted_behaviors') and k.get('evidence_requirement') and k.get('source') for k in key.values())
    rounds=[]
    for relative in ['evaluation/real','evaluation/mixed']:
        base=root/relative
        reviews={}
        shared_relation_ids={r['item_id'] for r in read_json(base/'candidate-items.json')['relations']}
        for name in ['sueda','mehmet']:
            entity_rows=rows(base/f'workbooks/{name}-entities.csv')
            relation_rows=rows(base/f'workbooks/{name}-relations.csv')
            attestation=read_json(base/f'workbooks/{name}-attestation.json')
            reviews[name]={'entity_labels':sum(bool(r['label']) for r in entity_rows),
                'entity_candidates':len(entity_rows),'relation_labels':sum(bool(r['label']) for r in relation_rows),
                'relation_candidates':len(relation_rows),
                'shared_relation_candidates':len(shared_relation_ids),
                'shared_relation_labels':sum(bool(r['label']) and r['item_id'] in shared_relation_ids for r in relation_rows),
                'supplemental_source_relation_rows':sum(r['item_id'] not in shared_relation_ids for r in relation_rows),
                'attestation_status':attestation['status'],
                'independent_human_attested':attestation.get('method')=='human' and attestation.get('independent') is True and attestation.get('status')=='complete'}
        corpus=rows(base/'workbooks/corpus-review.csv')
        qrels=rows(base/'workbooks/qrels.csv')
        from evaluation.independent_review import status as independent_status
        rounds.append({'direct_review_collection':independent_status(base.name,root),'directory':relative,'reviewers':reviews,'corpus_documents':len(corpus),
            'corpus_decisions':{k:sum(bool(r[k].strip()) for r in corpus) for k in ['sueda_include','mehmet_include','final_include','adjudicator']},
            'qrels_pairs':len(qrels),'qrels_fields':{k:sum(bool(r[k].strip()) for r in qrels) for k in ['sueda_grade','mehmet_grade','final_grade','adjudicator']}})
    identities=read_json(root/'evaluation/submission/contributor-identities.json')['mappings']
    return {'checked_at':utc_now(),'study_index':'evaluation/study-index.json',
        'pilot':{'consent_reports':len(pilot['participants']),
            'consent_methods':dict(Counter(p['consent_method'] for p in pilot['participants'])),
            'planned_tasks':len(assignments),'submitted_responses':len(responses),
            'scored_task_results':len(pilot['task_results']),'participants':by_participant,
            'task_key_content_complete':bool(content_complete),
            'task_key_review_method':pilot['protocol']['task_key_review_method'],
            'second_task_key_review':task_key_review_status(pilot_dir),
            'task_key_adjudication_complete':bool(finalized),
            'final_grading':finalized,
            'task_key_independently_adjudicated':pilot['protocol']['task_key_review_method']=='independently_adjudicated'},
        'annotation_rounds':rounds,
        'contributor_identities':{'project_account_mappings_confirmed':sum(m['github_commit_account_verified'] and m['team_mapping_confirmed'] for m in identities),
            'total_members':len(identities),'scope':'GitHub account authorship plus team-confirmed name mapping; not independent annotation or pilot measurement.'},
        'remaining_actual_inputs':_remaining_actual_inputs(rounds, assignments, responses, finalized),
        'measurement_limitations':['Free-text evidence and qualifying/policy explanations were not collected; unassessable criteria remain explicitly unmeasured.'],
        'complete_research_submission':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'evaluation/submission/readiness.json')
    args=parser.parse_args();result=report();write_json(args.out,result)
    print(f"Readiness saved to {args.out}: {result['pilot']['submitted_responses']}/{result['pilot']['planned_tasks']} responses; "
          f"{result['contributor_identities']['project_account_mappings_confirmed']}/4 project account mappings confirmed.")
