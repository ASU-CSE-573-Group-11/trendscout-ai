import json
import shutil

import pytest

from evaluation.archive_followup import replay
from evaluation.mixed_source_review import verify
from evaluation.real_round import ROOT


def test_mixed_review_is_complete_and_preserves_other_rater_columns():
    directory=ROOT/'evaluation/mixed'
    result=verify(directory)
    assert result['entities_reviewed']==276 and result['entities_accepted']==118
    assert result['relations_reviewed']==108 and result['mentions_accepted']==33
    assert result['qrels_reviewed']==1260 and result['positive_component_grades']==195
    assert result['independent_human_agreement']['status']=='computed_from_direct_source_reviews'


def test_sueda_relation_source_assisted_review_is_complete_but_not_independent():
    import csv
    from pathlib import Path

    directory = ROOT / 'evaluation/mixed'
    rows = list(csv.DictReader(
        (directory / 'workbooks/sueda-relations.csv').open(newline='', encoding='utf-8')
    ))
    assert len(rows) == 108
    assert all(row['label'].strip() in {'MENTIONS', 'NONE'} for row in rows)

    progress = json.loads(
        (directory / 'sueda-source-review/relation-review-complete.json').read_text(encoding='utf-8')
    )
    assert progress['relation_decisions'] == 108
    assert progress['mentions'] == 33
    assert progress['none'] == 75
    assert progress['independent_human_attestation'] is False
    assert progress['kappa_eligible'] is False


def test_mehmet_mixed_source_assisted_review_is_filled_but_not_independent():
    import csv

    directory = ROOT / 'evaluation/mixed'
    relations = list(csv.DictReader(
        (directory / 'workbooks/mehmet-relations.csv').open(newline='', encoding='utf-8')
    ))
    entities = list(csv.DictReader(
        (directory / 'workbooks/mehmet-entities.csv').open(newline='', encoding='utf-8')
    ))
    progress = json.loads(
        (directory / 'mehmet-source-assisted-review.json').read_text(encoding='utf-8')
    )
    assert len(relations) == 108
    assert len(entities) == 276
    assert progress['source_assisted_relations'] == 108
    assert progress['source_assisted_entities'] == 276
    assert progress['independent_human_attestation'] is False
    assert progress['kappa_eligible'] is False


def test_changed_review_cannot_pass_checksums(tmp_path):
    source=ROOT/'evaluation/mixed'
    shutil.copytree(source,tmp_path/'round')
    path=tmp_path/'round/workbooks/sueda-entities.csv'
    path.write_text(path.read_text().replace('Startup','Investor',1))
    with pytest.raises(ValueError,match='checksum'):
        verify(tmp_path/'round')


def test_archive_variant_replays_without_counting_a_new_company():
    result=replay(ROOT/'evaluation/cohort-archive-followup')
    assert result['additional_job_observations']==102
    assert result['merged_job_observations']==495
    assert result['comparisons'][0]['company_id']=='langchain'
    assert result['comparisons'][0]['net_posting_change']==0


def test_mehmet_independent_review_json_is_complete_but_source_assisted():
    data = json.loads(
        (ROOT / 'evaluation/independent-review/mixed/mehmet.json').read_text(encoding='utf-8')
    )
    assert len(data['decisions']['entities']) == 276
    assert len(data['decisions']['relations']) == 108
    assert data['complete'] is True
    assert data['method'] == 'team_authorized_source_assisted_review'
    assert data['independent_human_attestation'] is False
    assert data['kappa_eligible'] is False
