import hashlib
import json
from evaluation.entity_source_check import ROOT, OUTPUT, build


def test_source_check_replays_and_does_not_overwrite_seed_labels():
    p=ROOT/'evaluation/real/workbooks/sueda-entities.csv';before=hashlib.sha256(p.read_bytes()).hexdigest()
    result=build()
    assert result==json.loads((ROOT/OUTPUT).read_text())
    assert hashlib.sha256(p.read_bytes()).hexdigest()==before
    assert result['rounds']['real']['formally_valid_candidates']==418
    assert result['rounds']['mixed']['formally_valid_candidates']==276
    assert result['rounds']['real']['recommended_corrections']==0
    assert result['rounds']['real']['source_review_positive_labels']==142
    assert result['count_targets_used_to_choose_labels'] is False
    assert result['is_independent_annotation'] is False


def test_named_document_and_api_are_distinguished_from_imperatives():
    r=build()['rounds']['real'];rows=r['source_review_labels']
    assert all(x['source_review_final_label']=='NONE' for x in rows if x['entity_text'] in {'Documentation','Contributors','Record'})
    assert all(x['source_review_final_label']=='NONE' for x in rows if x['entity_text'] in {'Responses','Decisions','README','AGENTS.md'})
    assert all(c['rationale'] and c['entity_text'] in c['supporting_passage'] for c in r['corrections'])
