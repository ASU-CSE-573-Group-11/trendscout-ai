"""Build an evidence-backed coverage and outstanding-input report offline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evaluation.cohort_history import replay as replay_history
from evaluation.cohort_jobs import replay as replay_jobs
from evaluation.project_readiness import report as readiness
from evaluation.real_round import ROOT, annotation_agreement
from evaluation.mixed_source_review import verify as verify_mixed_review
from evaluation.archive_followup import replay as replay_archive_followup
from evaluation.pilot_analysis import summarize as summarize_pilot
from evaluation.cohort_identity import replay as replay_identity


def load_records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def report(root=ROOT):
    remaining_history=None
    remaining_history_path=root/'evaluation/remaining-history-discovery/review.json'
    if remaining_history_path.exists():
        from evaluation.remaining_history_review import build as build_remaining_history
        remaining_history=build_remaining_history(root)
        if json.loads(remaining_history_path.read_text())!=remaining_history:
            raise ValueError('Rebuild stale remaining-company history review')
    entity_check=None
    entity_path=root/'evaluation/submission/sueda-entity-source-check.json'
    if entity_path.exists():
        from evaluation.entity_source_check import build as build_entity_check
        entity_check=build_entity_check(root)
        if json.loads(entity_path.read_text())!=entity_check:
            raise ValueError('Rebuild stale entity source check')
    reconciliation=None
    reconciliation_path=root/'evaluation/mixed/relation-reconciliation.json'
    if reconciliation_path.exists():
        from evaluation.mixed_relation_reconciliation import build as build_reconciliation
        reconciliation=build_reconciliation(root)
        if json.loads(reconciliation_path.read_text())!=reconciliation:
            raise ValueError('Rebuild stale mixed relation reconciliation')
    from evaluation.ats_history import build as build_ats_history
    ats_history=build_ats_history(root/'evaluation/cohort-ats-history')
    if json.loads((root/'evaluation/cohort-ats-history/review.json').read_text())!=ats_history:
        raise ValueError('Rebuild stale ATS history review')
    from evaluation.career_history import build as build_career_history
    career_history=build_career_history(root/'evaluation/cohort-history-followup')
    from evaluation.question_coverage import build as build_question_coverage
    from evaluation.funding_review import build as build_funding_review
    question_coverage=build_question_coverage(root)
    funding_review=build_funding_review(root)
    for name, expected in [('question-coverage.json',question_coverage),('funding-source-review.json',funding_review)]:
        if json.loads((root/'evaluation/submission'/name).read_text()) != expected:
            raise ValueError('Rebuild stale source assessment: '+name)
    history=root/'evaluation/cohort-history-v2'
    jobs=root/'evaluation/cohort-job-history'
    history_check=replay_history(history)
    job_check=replay_jobs(jobs)
    mixed_review=verify_mixed_review(root/'evaluation/mixed')
    archive_followup=replay_archive_followup(root/'evaluation/cohort-archive-followup')
    identity_review=replay_identity(root/'evaluation/cohort-identity-review')
    cohort=json.loads((history/'cohort.json').read_text())
    job_manifest=json.loads((jobs/'manifest.json').read_text())
    weekly=load_records(history/'records.jsonl')
    documentary=load_records(root/'evaluation/sueda-delivery-corpus/study-records.jsonl')
    voices=load_records(root/'evaluation/sueda-evidence-extension/public-voice-records.jsonl')
    mixed=load_records(root/'evaluation/mixed/records.jsonl')
    companies=[]
    for c in cohort['companies']:
        if c['status']!='included':
            continue
        cid=c['company_id']
        entry=next(x for x in job_manifest['companies'] if x['company_id']==cid)
        weeks=[r for r in weekly if r['company_id']==cid]
        latest_followup=next((s for s in ats_history['snapshots'] if s['company_id']==cid and not s['archived']),None)
        native_followup=[s for s in career_history['snapshots'] if s['company_id']==cid and not s['archived']]
        scoped_current=None
        crew_current=None
        if remaining_history:
            current=[s for s in remaining_history['snapshots'].get(cid,[]) if not s['archived']]
            if current and current[0]['population']=='complete_official_career_list':
                native_followup=[{'specific_roles':current[0]['listed_count']}]
            elif current:
                scoped_current=current[0]
            if cid=='crewai':crew_current=remaining_history['crewai_current_board']
        companies.append({'company_id':cid,'name':c['name'],
            'github_complete_weeks':len(weeks),
            'default_branch_commits':sum(r['metadata']['activity_window']['commit_count'] for r in weeks),
            'dated_documentary_records':sum(r.get('company_id')==cid for r in documentary),
            'dated_public_voice_origins':len({r['source_url'] for r in voices if r.get('company_id')==cid}),
            'primary_funding_documents_in_mixed_round':sum(r['source_type']=='funding' and r.get('company_id')==cid for r in mixed),
            'current_listed_postings':crew_current['listed_count'] if crew_current else len(latest_followup['listings']) if latest_followup else entry['current_listed'],
            'current_scoped_listed_roles':scoped_current['listed_count'] if scoped_current else None,
            'current_scoped_population':scoped_current['population'] if scoped_current else None,
            'current_native_career_specific_roles':native_followup[0]['specific_roles'] if native_followup else None,
            'baseline_in_window_job_comparison':entry['historical_in_window'],
            'in_window_job_comparison':cid in (remaining_history['summary']['complete_official_population_history_companies'] if remaining_history else ats_history['summary']['historical_companies']),
            'job_comparisons':[{'board':b['slug'],**comp} for b in entry['boards'] for comp in b.get('comparisons',[])],
            'has_comparable_posting_history':cid in (remaining_history['summary']['complete_official_population_history_companies'] if remaining_history else ats_history['summary']['historical_companies']),
            'additional_scoped_history':[c for c in remaining_history['comparisons'] if c['company_id']==cid and c['population']!='complete_official_career_list'] if remaining_history else [],
            'latest_native_history_comparisons':[c for c in remaining_history['comparisons'] if c['company_id']==cid and c['population']=='complete_official_career_list'] if remaining_history else [],
            'followup_ats_comparisons':[c for c in ats_history['comparisons'] if c['company_id']==cid],
            'followup_career_list_comparisons':[c for c in career_history['comparisons'] if c['company_id']==cid]})
    study=readiness(root)
    pilot_summary=summarize_pilot(root/'evaluation/real')
    direct=next(r['direct_review_collection'] for r in study['annotation_rounds'] if r['directory']=='evaluation/real')
    if direct['pairwise_agreement']:
        agreement={'status':'computed_from_direct_source_reviews','results':direct['pairwise_agreement']['results'],
                   'review_file_sha256':direct['pairwise_agreement']['review_file_sha256'],
                   'method':direct['pairwise_agreement']['method']}
    else:
        try:
            agreement={'status':'computed','results':annotation_agreement(root/'evaluation/real')}
        except ValueError as exc:
            agreement={'status':'awaiting_independent_reviews','cohen_kappa':None,'reason':str(exc),
                       'direct_source_collection':direct}
    return {'status':'partial_completion_real_inputs_outstanding',
        'basis':'Current saved public sources and actual study records; no participant measurements inferred.',
        'history_verification':history_check,'job_verification':job_check,
        'identity_source_check':identity_review,
        'career_history_followup':career_history['summary'],
        'ats_history_followup':ats_history['summary'],
        'remaining_company_history_review':remaining_history['summary'] if remaining_history else None,
        'question_coverage':question_coverage['summary'],
        'funding_source_review':funding_review['summary'],
        'mixed_first_source_review':mixed_review,
        'entity_source_quality_check':{k:{n:v for n,v in r.items() if n not in ['corrections','source_review_labels']} for k,r in entity_check['rounds'].items()} if entity_check else None,
        'mixed_personal_relation_reconciliation':{'summary':reconciliation['summary'],'pre_reconciliation_agreement':reconciliation['pre_reconciliation_agreement'],'method':reconciliation['method'],'is_independent_gold_standard':False} if reconciliation else None,
        'job_archive_followup':archive_followup,
        'coverage':companies,'agreement':agreement,
        'annotation_rounds':study['annotation_rounds'],'pilot':study['pilot'],
        'pilot_measurement_summary':pilot_summary,
        'remaining':[(f"Complete official-population histories remain unavailable for {len(remaining_history['summary']['companies_without_complete_official_population_history'])} of 18 companies. Four additional scoped channels are available; CrewAI has historical advertisements but no complete board baseline. Weekly hiring trajectories remain unestablished." if remaining_history else f"Historical job comparisons for {len(ats_history['summary']['remaining_companies_without_comparable_history'])} of 18 companies remain unavailable; weekly hiring trajectories remain unestablished."),
            'Independent personal reviews and corresponding attestations; second labels and final adjudication.',
            *([f"{pilot_summary['remaining_tasks']} additional actual participant task responses."] if pilot_summary['remaining_tasks'] else []),
            *([] if pilot_summary['task_key_adjudication_complete'] else ['Independent task-key review and final correctness grading.'])],
        'pilot_measurement_limitations':study['measurement_limitations'],
        'complete_research_submission':False,
        'input_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [history/'manifest.json',jobs/'manifest.json',
             root/'evaluation/cohort-identity-review/manifest.json',
             root/'evaluation/submission/question-coverage.json',
             root/'evaluation/cohort-history-followup/review.json',
             root/'evaluation/cohort-ats-history/review.json',
             root/'evaluation/submission/funding-source-review.json',
             root/'evaluation/cohort-identity-review/usable-profiles.json',
             root/'evaluation/real/pilot-session/responses.json',root/'evaluation/real/trust-pilot.json',
             root/'evaluation/real/workbooks/sueda-attestation.json',root/'evaluation/real/workbooks/mehmet-attestation.json']}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'evaluation/submission/sueda-completion.json')
    args=parser.parse_args()
    result=report()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'history':result['history_verification'],'jobs':result['job_verification'],
        'agreement':result['agreement']['status'],'pilot_responses':result['pilot']['submitted_responses']},indent=2))
