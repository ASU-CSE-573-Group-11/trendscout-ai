"""Regression checks for real-source evaluation and human-result boundaries."""
import csv
import json
from pathlib import Path

import pytest

from evaluation.real_round import ROOT, adjudicated_qrels, annotation_agreement, frozen_records, load_csv
from interface.agent import AgentConfig, TrendScoutAgent
from collectors.records import make_record


def test_sueda_source_review_has_200_accepted_entities():
    import csv
    path = ROOT / 'evaluation/real/workbooks/sueda-entities.csv'
    rows = list(csv.DictReader(path.open(newline='', encoding='utf-8')))
    accepted = sum(row['label'].strip() not in ('', 'NONE') for row in rows)
    assert accepted == 200
    progress = json.loads(
        (ROOT / 'evaluation/real/sueda-entity-progress.json').read_text(encoding='utf-8')
    )
    assert progress['target_met'] is True
    assert progress['independent_human_attestation'] is False


def test_sueda_relation_source_review_expands_to_target():
    import csv
    path = ROOT / 'evaluation/real/workbooks/sueda-relations.csv'
    rows = list(csv.DictReader(path.open(newline='', encoding='utf-8')))
    accepted = sum(row['label'].strip() not in ('', 'NONE') for row in rows)
    assert len(rows) == 182
    assert accepted == 90
    assert 80 <= accepted <= 100


def test_frozen_real_corpus_is_valid_unique_and_traceable():
    records = frozen_records(ROOT / 'evaluation/real')
    assert len(records) == 45
    assert len({r['source_url'] for r in records}) == 45
    assert {r['company_id'] for r in records} == {'langchain', 'llamaindex', 'crewai'}
    assert all(r['metadata']['synthetic'] is False for r in records)


def test_empty_human_inputs_cannot_produce_agreement_or_qrels():
    with pytest.raises(ValueError, match='attestation'):
        annotation_agreement(ROOT / 'evaluation/real')
    with pytest.raises(ValueError, match='grades'):
        adjudicated_qrels(ROOT / 'evaluation/real')


def test_csv_agreement_rejects_duplicate_item_ids(tmp_path):
    path = tmp_path / 'labels.csv'
    path.write_text('item_id,label\nx,Startup\nx,Product\n')
    with pytest.raises(ValueError, match='duplicate'):
        load_csv(path, 'item_id', 'label')


def test_zero_origin_graph_aggregate_cannot_become_a_supporting_citation():
    from interface.agent import _build_citations
    from retrieval.graph_access import GraphResult
    result = GraphResult(purpose='independent_origins', template=None,
                         parameters={'company_id': 'missing'},
                         rows=[{'company_id': 'missing', 'origin_cluster_ids': [], 'count': 0}])
    assert _build_citations([], [result], []) == []


def test_single_category_kappa_is_undefined():
    from evaluation.compute_agreement import cohen_kappa
    with pytest.raises(ValueError, match='undefined'):
        cohen_kappa({'x': 'Startup'}, {'x': 'Startup'})


def test_renaming_simulated_status_does_not_make_human_labels(tmp_path):
    from evaluation.compute_agreement import load_annotations
    path = tmp_path / 'labels.json'
    path.write_text(json.dumps({'status': 'complete', 'not_human_annotation': True,
                                'annotations': {'x': 'Startup'}}))
    with pytest.raises(ValueError, match='ineligible'):
        load_annotations(path)


@pytest.mark.parametrize('sparse', [False, True])
def test_independent_round_computes_agreement_without_adjudicated_labels(tmp_path, sparse):
    import hashlib
    import shutil
    from evaluation.real_round import write_json, read_json
    source = ROOT / 'evaluation/real'
    for name in ['manifest.json', 'records.jsonl', 'round-inputs.json', 'questions.json',
                 'candidate-items.json', 'guidelines.json']:
        shutil.copy(source / name, tmp_path / name)
    shutil.copytree(source / 'sources', tmp_path / 'sources')
    (tmp_path / 'workbooks').mkdir()
    for name in ['sueda', 'mehmet']:
        hashes = {}
        for kind in ['entities', 'relations']:
            rows = read_json(source / 'candidate-items.json')[kind]
            for index, row in enumerate(rows):
                row['label'] = ('Product' if index % 2 else 'Technology') if kind == 'entities' else ('MENTIONS' if index < 90 else 'NONE')
                if sparse and index > 1:
                    row['label'] = 'NONE'
            path = tmp_path / 'workbooks' / f'{name}-{kind}.csv'
            with path.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            hashes[kind] = hashlib.sha256(path.read_bytes()).hexdigest()
        write_json(tmp_path / 'workbooks' / f'{name}-attestation.json', {
            'status': 'complete', 'method': 'human', 'independent': True,
            'completed_at': '2026-11-20T12:00:00Z', 'workbook_sha256': hashes,
            'snapshot_sha256': read_json(source / 'manifest.json')['snapshot_sha256']})
    report = annotation_agreement(tmp_path)
    assert report['entities']['shared_items'] == 418
    assert report['relations']['shared_items'] == 126
    assert report['entities']['cohen_kappa'] == 1
    assert report['relations']['cohen_kappa'] == 1
    assert report['entities']['planned_positive_target_met_by_reviewer']['sueda'] is (not sparse)
    assert report['relations']['planned_positive_target_met_by_reviewer']['mehmet'] is (not sparse)
    # Test-only labels live exclusively in tmp_path; no study file is modified.


def test_source_reviews_cover_both_frozen_studies_and_ground_every_positive():
    from evaluation.real_round import source_reviewed_qrels
    base = ROOT / 'evaluation/real'
    original = source_reviewed_qrels(base, base / 'source-reviewed-qrels.json')
    release = source_reviewed_qrels(base, base / 'release-study/source-reviewed-qrels.json', base / 'release-study')
    assert len(original['judgments']) == len(release['judgments']) == 1260
    assert original['coverage']['positive_pairs'] == 0
    assert release['coverage']['positive_pairs'] == 28
    assert not original['human_adjudicated'] and not release['human_adjudicated']
    assert len(release['qrels']) == 28
    assert all(sum(g > 0 for g in grades.values()) == 1 for grades in release['qrels'].values())


def test_source_review_rejects_ungrounded_positive_quote(tmp_path):
    from evaluation.real_round import source_reviewed_qrels, read_json, write_json
    base = ROOT / 'evaluation/real'
    payload = read_json(base / 'release-study/source-reviewed-qrels.json')
    next(row for row in payload['judgments'] if row['grade'] > 0)['quote'] = 'This passage is fabricated.'
    path = tmp_path / 'qrels.json'
    write_json(path, payload)
    with pytest.raises(ValueError, match='exact source quote'):
        source_reviewed_qrels(base, path, base / 'release-study')


def test_source_review_rejects_duplicate_judgments(tmp_path):
    from evaluation.real_round import source_reviewed_qrels, read_json, write_json
    base = ROOT / 'evaluation/real'
    payload = read_json(base / 'source-reviewed-qrels.json')
    payload['judgments'].append(payload['judgments'][0])
    path = tmp_path / 'qrels.json'
    write_json(path, payload)
    with pytest.raises(ValueError, match='exactly once'):
        source_reviewed_qrels(base, path)


def test_zero_filled_trend_bins_cannot_become_supporting_citations():
    from types import SimpleNamespace
    from interface.agent import _build_citations
    empty_bin = SimpleNamespace(origin_cluster_ids=(), record_ids=())
    assert _build_citations([], [], [empty_bin]) == []
