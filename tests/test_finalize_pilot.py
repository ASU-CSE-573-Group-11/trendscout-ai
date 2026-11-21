import json
import shutil

import pytest

from evaluation.finalize_pilot import grade_response,verify
from evaluation.pilot_session import integrate_response_results
from evaluation.real_round import ROOT,read_json


@pytest.fixture
def finalized_round(tmp_path):
    source=ROOT/'evaluation/real'
    for name in ['manifest.json','records.jsonl','trust-pilot.json']:
        shutil.copy(source/name,tmp_path/name)
    shutil.copytree(source/'sources',tmp_path/'sources')
    shutil.copytree(source/'pilot-session',tmp_path/'pilot-session')
    (tmp_path/'sueda-review').mkdir()
    shutil.copy(source/'sueda-review/pilot-evidence-policy.md',tmp_path/'sueda-review/pilot-evidence-policy.md')
    return tmp_path


def test_final_scores_are_reproducible_and_missing_explanations_stay_unmeasured(finalized_round):
    raw=finalized_round/'pilot-session/responses.json';before=raw.read_bytes()
    result=verify(finalized_round)
    assert result['adjudication_complete'] and result['responses']==30
    assert result['metrics']['status_correct']=={'correct':1,'assessed':30,'not_assessed':0,'accuracy':1/30}
    assert result['metrics']['evidence_correct']['assessed']==0
    assert result['metrics']['evidence_correct']['not_assessed']==30
    assert result['metrics']['evidence_correct']['accuracy'] is None
    assert not result['full_protocol_measurement_complete']
    assert raw.read_bytes()==before


def test_legacy_integration_cannot_convert_missing_explanations_to_false(finalized_round):
    path=finalized_round/'trust-pilot.json';pilot=read_json(path)
    for row in pilot['task_results']:row['evidence_correct']=False
    path.write_text(json.dumps(pilot))
    raw=finalized_round/'pilot-session/responses.json';before=raw.read_bytes()
    integrate_response_results(finalized_round)
    pilot=read_json(path)
    assert all(r['evidence_correct'] is None for r in pilot['task_results'])
    assert verify(finalized_round)['legacy_pilot_container_matches_final_grading']
    assert raw.read_bytes()==before
    assert list((finalized_round/'pilot-session').glob('legacy-source-grading-*.json'))


@pytest.mark.parametrize('target',['raw','metrics'])
def test_changed_inputs_or_scores_are_rejected(finalized_round,target):
    session=finalized_round/'pilot-session'
    if target=='raw':
        path=session/'responses.json';value=read_json(path);value['responses'][0]['evidence_state']='stale'
    else:
        path=session/'final-grading.json';value=read_json(path);value['metrics']['status_correct']['correct']+=1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):verify(finalized_round)


@pytest.mark.parametrize('action,expected',[('answer',False),('qualify',None),('abstain',True)])
def test_qualification_without_recorded_explanation_is_not_invented(action,expected):
    raw={'participant_id':'TEST','question_id':'TEST','condition':'TEST','order':1,
        'duration_seconds':10,'confidence':3,'evidence_state':'insufficient','action':action}
    key={'expected_state':'insufficient','accepted_behaviors':['abstain','qualify_with_missing_evidence']}
    result=grade_response(raw,key)
    assert result['abstention_correct'] is expected
    assert result['evidence_correct'] is None
