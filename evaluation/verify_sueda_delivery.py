"""Verify Sueda's prepared collection and single-review deliverables offline.

This check does not certify paired annotation, participant measurements, or
the project's primary research success criterion.
"""
from __future__ import annotations

import csv
import hashlib
import json

from collectors.snapshot import replay
from evaluation.annotation_packet import unique, validate as validate_packet
from evaluation.real_round import ROOT, frozen_records, read_json, source_reviewed_qrels


def rows(path):
    with path.open(newline='',encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def exact_keys(items, key, expected, description):
    actual = unique(items, key, description)
    if actual != set(expected):
        raise ValueError('missing or unknown ' + description)


def verify_study(directory, study):
    """Bind metrics to the actual frozen inputs and saved answer bundles."""
    qrels_path = study / 'source-reviewed-qrels.json'
    judgments = source_reviewed_qrels(directory, qrels_path, study)
    qrels_digest = hashlib.sha256(qrels_path.read_bytes()).hexdigest()
    questions = {q['question_id'] for q in read_json(study / 'questions.json')['questions']}
    provenance = read_json(study / 'run-provenance.json')
    if provenance['snapshot_sha256'] != judgments['snapshot_sha256'] or provenance['questions_sha256'] != judgments['questions_sha256']:
        raise ValueError('answer run input checksum mismatch')
    if set(provenance['answers']) != {'bm25.jsonl.gz', 'dense.jsonl.gz', 'graph_only.jsonl.gz', 'hybrid.jsonl.gz'}:
        raise ValueError('all four answer conditions required')
    from evaluation.metrics import load_answers, load_qrels, load_seed_expectations, score_condition
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(read_json(ROOT / 'schemas/answer.schema.json'))
    saved_bundles = {}
    for name, digest in provenance['answers'].items():
        path = study / 'answers' / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('saved answer checksum mismatch')
        bundles = load_answers(path)
        exact_keys(bundles, lambda b: b['question_id'], questions, 'answer question IDs')
        for bundle in bundles:
            validator.validate(bundle)
        saved_bundles[name[:-len('.jsonl.gz')]] = bundles
    scored = read_json(study / 'scored-metrics.json')
    ranked = read_json(study / 'retrieval-metrics.json')
    if scored.get('source_qrels_sha256') != qrels_digest or ranked.get('qrels_sha256') != qrels_digest:
        raise ValueError('scored report qrels checksum mismatch')
    if ranked.get('snapshot_sha256') != judgments['snapshot_sha256'] or ranked.get('questions_sha256') != judgments['questions_sha256']:
        raise ValueError('ranking report input checksum mismatch')
    exact_keys(scored['conditions'], lambda c: c['condition'], {'bm25', 'dense', 'graph_only', 'hybrid'}, 'scored conditions')
    exact_keys(ranked['conditions'], lambda c: c['condition'], {'bm25', 'dense', 'hybrid'}, 'ranked conditions')
    for condition in ranked['conditions']:
        exact_keys(condition['per_question'], lambda q: q['question_id'], questions, 'ranked question IDs')
        for question in condition['per_question']:
            unique(question['ranking'], lambda r: r['record_id'], 'ranked record IDs')
    relevance = load_qrels(qrels_path)
    expectations = load_seed_expectations(study / 'questions.json')
    for condition in scored['conditions']:
        recomputed = score_condition(saved_bundles[condition['condition']], condition=condition['condition'],
            qrels=relevance, k=scored['k'], match=scored['match'], expectations=expectations).as_dict()
        if json.dumps(recomputed, sort_keys=True) != json.dumps(condition, sort_keys=True):
            raise ValueError('saved answer metrics differ from recomputed values')
    return len(questions) * len(provenance['answers'])


def verify(root=ROOT):
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
    ats_result=build_ats_history(root/'evaluation/cohort-ats-history')
    if json.loads((root/'evaluation/cohort-ats-history/review.json').read_text())!=ats_result:
        raise ValueError('Rebuild stale ATS review')
    from evaluation.career_history import build as build_career_history
    career_result=build_career_history(root/'evaluation/cohort-history-followup')
    if json.loads((root/'evaluation/cohort-history-followup/review.json').read_text())!=career_result:
        raise ValueError('Rebuild stale career history review')
    from evaluation.question_coverage import build as build_question_coverage
    from evaluation.funding_review import build as build_funding_review
    coverage_result=build_question_coverage(root)
    funding_result=build_funding_review(root)
    for name, expected in [('question-coverage.json',coverage_result),('funding-source-review.json',funding_result)]:
        if json.loads((root/'evaluation/submission'/name).read_text()) != expected:
            raise ValueError('Rebuild stale source assessment: '+name)
    from evaluation.cohort_identity import replay as replay_identity
    identity_result=replay_identity(root/'evaluation/cohort-identity-review')
    from evaluation.mixed_source_review import verify as verify_mixed_review
    from evaluation.archive_followup import replay as replay_archive_followup
    mixed_review_result=verify_mixed_review(root/'evaluation/mixed')
    archive_followup_result=replay_archive_followup(root/'evaluation/cohort-archive-followup')
    from collectors.evidence_archives import replay as replay_extension
    extension_result = replay_extension(root/'evaluation/sueda-evidence-extension')
    from evaluation.cohort_history import replay as replay_history
    from evaluation.cohort_jobs import replay as replay_jobs
    history_result = replay_history(root/'evaluation/cohort-history-v2')
    job_result = replay_jobs(root/'evaluation/cohort-job-history')
    source=root/'evaluation/sueda-delivery-corpus'
    replay_result=replay(source)
    records=[json.loads(line) for line in (source/'records.jsonl').read_text().splitlines()]
    if len({r['record_id'] for r in records})!=len(records):
        raise ValueError('duplicate collection record IDs')
    if not {'news','public_voice','company'} <= {r['source_type'] for r in records}:
        raise ValueError('missing documentary source family')
    study=[json.loads(line) for line in (source/'study-records.jsonl').read_text().splitlines()]
    expected=[r for r in records if r['source_type']!='reference' and r['published_at']
              and '2025-11-01'<=r['published_at']<'2026-11-21']
    exact_keys(study, lambda r: r['record_id'], [r['record_id'] for r in expected], 'study record IDs')
    by_source_id = {r['record_id']: r for r in records}
    if any(record != by_source_id[record['record_id']] for record in study):
        raise ValueError('study slice content differs from frozen source')
    summary = read_json(source / 'delivery-summary.json')
    expected_types = {kind: sum(r['source_type'] == kind for r in records) for kind in {r['source_type'] for r in records}}
    expected_study_types = {kind: sum(r['source_type'] == kind for r in study) for kind in {r['source_type'] for r in study}}
    if summary['source_types'] != expected_types or summary['study_source_types'] != expected_study_types or summary['all_source_records'] != len(records) or summary['study_document_count'] != len(study):
        raise ValueError('documentary summary differs from source records')
    directory=root/'evaluation/real'
    original={r['record_id']:r for r in frozen_records(directory)}
    audit=directory/'sueda-review'
    candidates = read_json(directory / 'candidate-items.json')
    guidelines = read_json(directory / 'guidelines.json')
    primary_entities = rows(directory/'workbooks/sueda-entities.csv')
    exact_keys(primary_entities, lambda r: r['item_id'], [r['item_id'] for r in candidates['entities']], 'entity candidate IDs')
    primary_relations = rows(directory/'workbooks/sueda-relations.csv')
    from evaluation.relation_extension import validate as validate_relation_extension
    relation_extension=validate_relation_extension(directory,candidates,original,primary_relations)
    entity_rows=rows(directory/'workbooks/sueda-entities.csv')+rows(audit/'additional-entities.csv')
    accepted=[]
    for row in entity_rows:
        text=original[row['document_id']]['text']
        if row['label'] not in set(guidelines['entity_types']) | {'NONE'} or not row['notes'].strip() or not 0 <= int(row['start']) < int(row['end']) <= len(text) or text[int(row['start']):int(row['end'])]!=row['entity_text']:
            raise ValueError('missing or ungrounded entity label')
        if row['label']!='NONE':
            accepted.append((row['document_id'],int(row['start']),int(row['end'])))
    if len(set(accepted))!=len(accepted) or len(accepted)<200:
        raise ValueError('200+ distinct grounded entity mentions required')
    relations=rows(audit/'relations-90.csv')
    if not 80<=len(relations)<=100 or len({(r['document_id'],r['object']) for r in relations})!=len(relations):
        raise ValueError('80-100 distinct documentary relation facts required')
    if any(r['object'] not in r['span_text'] or r['span_text'] not in original[r['document_id']]['text'] for r in relations):
        raise ValueError('ungrounded relation passage')
    corpus=rows(directory/'workbooks/corpus-review.csv')
    exact_keys(corpus, lambda r: r['document_id'], original, 'corpus document IDs')
    if any(r['sueda_include'] not in {'yes','no'} or not r['notes'].strip() or r['source_url'] != original[r['document_id']]['source_url'] for r in corpus):
        raise ValueError('missing first-pass corpus decisions')
    qrels=rows(directory/'workbooks/qrels.csv')
    expected_qrels={(r['question_id'],r['record_id']):r['grade']
                    for r in read_json(directory/'source-reviewed-qrels.json')['judgments']}
    exact_keys(qrels, lambda r: (r['question_id'],r['record_id']), expected_qrels, 'qrels pairs')
    if any(r['sueda_grade']!=str(expected_qrels[(r['question_id'],r['record_id'])]) or not r['notes'].strip() or r['source_url'] != original[r['record_id']]['source_url'] for r in qrels):
        raise ValueError('first-pass relevance grades differ from source judgments')
    attestation = read_json(directory / 'workbooks/sueda-attestation.json')
    for kind in ['entities', 'relations']:
        if attestation['workbook_sha256'][kind] != hashlib.sha256((directory / f'workbooks/sueda-{kind}.csv').read_bytes()).hexdigest():
            raise ValueError('first-review workbook checksum mismatch')
    packet = audit / 'candidate-review-v2'
    packet_manifest = read_json(packet / 'manifest.json')
    if packet_manifest['base_snapshot_sha256'] != read_json(directory / 'manifest.json')['snapshot_sha256'] or packet_manifest['base_candidate_items_sha256'] != hashlib.sha256((directory / 'candidate-items.json').read_bytes()).hexdigest():
        raise ValueError('annotation packet base checksum mismatch')
    packet_result = validate_packet(packet, list(original.values()), guidelines)
    pilot=read_json(directory/'trust-pilot.json')
    from evaluation.pilot_analysis import summarize as summarize_pilot
    pilot_measurements=summarize_pilot(directory)
    if set(pilot['protocol']['task_key'])!=set(pilot['protocol']['task_ids']):
        raise ValueError('pilot task key incomplete')
    policy=audit/'pilot-evidence-policy.md'
    if hashlib.sha256(policy.read_bytes()).hexdigest()!=pilot['protocol']['policy_sha256']:
        raise ValueError('pilot policy checksum mismatch')
    answer_bundles = sum(verify_study(directory, study) for study in [directory, directory / 'release-study'])
    return {'status':'prepared_source_review_verified',
        'dated_evidence_extension':extension_result,
        'cohort_history':history_result, 'cohort_jobs':job_result,
        'cohort_identity_source_check':identity_result,
        'career_history_followup':career_result['summary'],
        'ats_history_followup':ats_result['summary'],
        'remaining_company_history_review':remaining_history['summary'] if remaining_history else None,
        'question_coverage':coverage_result['summary'],
        'funding_source_review':funding_result['summary'],
        'mixed_first_source_review':mixed_review_result,
        'entity_source_quality_check':{k:{n:v for n,v in r.items() if n not in ['corrections','source_review_labels']} for k,r in entity_check['rounds'].items()} if entity_check else None,
        'mixed_personal_relation_reconciliation':reconciliation['summary'] if reconciliation else None,
        'job_archive_followup':archive_followup_result,
        'source_records':replay_result['records'],'study_documents':len(study),
        'source_reviewed_entity_mentions':len(accepted),
        'source_relation_extension':relation_extension,'documentary_relations':len(relations),
        'corpus_first_decisions':len(corpus),'qrels_first_grades':len(qrels),
        'annotation_packet':packet_result, 'verified_saved_answers':answer_bundles,
        'remaining_project_inputs':['Independent second review and adjudication',
            *([f"{pilot_measurements['remaining_tasks']} actual pilot task responses"] if pilot_measurements['remaining_tasks'] else []),
            *([] if pilot_measurements['task_key_adjudication_complete'] else ['Reviewed task key and final correctness grading'])],
        'cohen_kappa':None,'consent_reports':len(pilot.get('participants', [])),
        'pilot_measurements':pilot_measurements,
        'participant_results_supplied':bool(pilot.get('task_results'))}


if __name__=='__main__':
    print(json.dumps(verify(),indent=2))
