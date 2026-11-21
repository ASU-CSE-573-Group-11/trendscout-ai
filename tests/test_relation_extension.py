import copy
import csv
import json
import pytest
from evaluation.real_round import ROOT
from evaluation.relation_extension import validate


def inputs():
    d=ROOT/'evaluation/real'
    return d,json.loads((d/'candidate-items.json').read_text()),{r['record_id']:r for r in map(json.loads,(d/'records.jsonl').read_text().splitlines())},list(csv.DictReader((d/'workbooks/sueda-relations.csv').open()))


def test_registered_supplement_has_real_passages_without_changing_shared_pool():
    d,c,r,rows=inputs();result=validate(d,c,r,rows)
    assert result['shared_candidate_items']==126
    assert result['supplemental_source_items']==56
    assert result['positive_mention_occurrences']==88
    assert result['distinct_document_object_facts']==86
    assert result['supplement_is_independent_paired_annotation'] is False


def test_empty_supplement_passage_or_unknown_row_is_rejected():
    d,c,r,rows=inputs();changed=copy.deepcopy(rows);changed[-1]['span_text']=''
    with pytest.raises(ValueError,match='fields differ'):
        validate(d,c,r,changed)
    changed=copy.deepcopy(rows);changed[-1]['item_id']='unregistered-source-row'
    with pytest.raises(ValueError,match='unknown source relation'):
        validate(d,c,r,changed)
