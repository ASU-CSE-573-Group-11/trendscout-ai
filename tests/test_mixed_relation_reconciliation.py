import hashlib
import json
import pytest
from evaluation import mixed_relation_reconciliation as review


def test_reconciliation_replays_preserving_original_input_and_pre_resolution_metrics():
    p=review.ROOT/'evaluation/mixed/relation-approval-packet.json'
    before=hashlib.sha256(p.read_bytes()).hexdigest()
    result=review.build()
    assert result==json.loads((review.ROOT/review.OUTPUT).read_text())
    assert hashlib.sha256(p.read_bytes()).hexdigest()==before
    assert result['summary']['reviewer_disagreements_reviewed']==69
    assert result['summary']['disagreement_resolution_label_counts']=={'MENTIONS':2,'NONE':67}
    assert result['pre_reconciliation_agreement']['matching_labels']==39
    assert result['pre_reconciliation_agreement']['cohen_kappa']==pytest.approx(0.009569377990430578)
    assert result['is_independent_gold_standard'] is False


def test_consensus_is_not_assumed_to_be_source_correct():
    result=review.build();by_id={r['item_id']:r for r in result['decisions']}
    flags=[by_id[k] for k in result['agreed_label_quality_flag_ids']]
    assert {r['object'] for r in flags}=={'June','Paul','Counts'}
    assert all(r['original_reviewer_labels']=={'sueda':'MENTIONS','mehmet':'MENTIONS'} and r['source_review_final_label']=='NONE' for r in flags)
    for row in result['decisions']:
        assert row['object'] in row['supporting_passage']
        assert row['passage_end']-row['passage_start']==len(row['supporting_passage'])
        assert row['rationale']


def test_unreviewed_object_requires_explicit_source_review(monkeypatch):
    monkeypatch.delitem(review.POLICY,'LangChain')
    with pytest.raises(ValueError,match='New object requires source-policy review'):
        review.build()
