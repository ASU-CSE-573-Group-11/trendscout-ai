from pathlib import Path

from evaluation.real_round import ROOT,read_json
from evaluation.task_key_audit import audit


def test_source_audit_preserves_actual_records_and_does_not_adjudicate():
    directory=ROOT/'evaluation/real'
    paths=[directory/'pilot-session/task-key-second-review.json',directory/'pilot-session/responses.json']
    before=[p.read_bytes() for p in paths]
    result=audit(directory)
    assert len(result['proposals'])==6
    assert result['source_inventory']['event_types']=={'software_release':45}
    assert result['second_review']['recorded_decisions']==6
    assert not result['final_adjudication_complete']
    assert result['state_match_sensitivity']['initial_source_key']['responses']==30
    assert not result['independent_entity_relation_agreement_established']
    assert before==[p.read_bytes() for p in paths]
