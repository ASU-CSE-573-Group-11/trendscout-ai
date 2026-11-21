"""Pilot instrumentation tests. All example responses live only in tmp_path."""
import json
import shutil

import pytest

from evaluation.pilot_session import prepare, record_response
from evaluation.real_round import ROOT, read_json, write_json


@pytest.fixture
def session(tmp_path):
    source=ROOT/'evaluation/real'
    shutil.copy(source/'trust-pilot.json',tmp_path/'trust-pilot.json')
    pilot=read_json(tmp_path/'trust-pilot.json');pilot['task_results']=[]
    write_json(tmp_path/'trust-pilot.json',pilot)
    (tmp_path/'answers').mkdir()
    shutil.copy(source/'answers/hybrid.jsonl.gz',tmp_path/'answers/hybrid.jsonl.gz')
    prepare(tmp_path)
    return tmp_path


def first_response(directory):
    assignment=next(a for a in read_json(directory/'pilot-session/assignments.json')['assignments']
                    if a['participant_id']=='P05' and a['order']==1)
    return {'participant_id':'P05','question_id':assignment['question_id'],
            'evidence_state':'insufficient','evidence_numbers':[],
            'action':'abstain','confidence':3,'duration_seconds':15}


def test_planning_randomizes_conditions_and_order_without_inventing_responses(session):
    assignments=read_json(session/'pilot-session/assignments.json')['assignments']
    assert len(assignments)==30
    for pid in {a['participant_id'] for a in assignments}:
        own=[a for a in assignments if a['participant_id']==pid]
        assert len({a['question_id'] for a in own})==6
        assert {a['order'] for a in own}==set(range(1,7))
        assert sum(a['condition']=='citations_only' for a in own)==3
    assert read_json(session/'pilot-session/responses.json')['responses']==[]
    assert read_json(session/'trust-pilot.json')['task_results']==[]


def test_recording_retains_reported_response_without_manufacturing_correctness(session):
    response=first_response(session)
    record_response(session,response)
    saved=read_json(session/'pilot-session/responses.json')['responses'][0]
    assert saved['duration_seconds']==15 and saved['timing_method']=='participant_reported'
    assert saved['grading_status']=='pending_task_key_adjudication'
    assert not {'status_correct','evidence_correct','abstention_correct'} & saved.keys()
    assert read_json(session/'trust-pilot.json')['task_results']==[]
    with pytest.raises(ValueError,match='already recorded'):
        record_response(session,response)


@pytest.mark.parametrize('field,value', [('confidence',True),('confidence',0),
    ('duration_seconds',True),('duration_seconds',float('nan')),('duration_seconds',0),
    ('evidence_numbers',[999])])
def test_invalid_measurements_are_rejected(session,field,value):
    response=first_response(session);response[field]=value
    with pytest.raises(ValueError):record_response(session,response)
    assert read_json(session/'pilot-session/responses.json')['responses']==[]


def test_no_response_is_recorded_without_consent_or_in_the_wrong_order(session):
    pilot=read_json(session/'trust-pilot.json')
    next(p for p in pilot['participants'] if p['participant_id']=='P05')['consent_confirmed']=False
    write_json(session/'trust-pilot.json',pilot)
    with pytest.raises(ValueError,match='consent'):record_response(session,first_response(session))
    next(p for p in pilot['participants'] if p['participant_id']=='P05')['consent_confirmed']=True
    write_json(session/'trust-pilot.json',pilot)
    response=first_response(session)
    response['question_id']=next(a['question_id'] for a in read_json(session/'pilot-session/assignments.json')['assignments']
                                 if a['participant_id']=='P05' and a['order']==2)
    with pytest.raises(ValueError,match='presentation order'):record_response(session,response)


def test_frozen_stimuli_cannot_be_changed_after_planning(session):
    path=session/'pilot-session/stimuli.json'
    stimuli=read_json(path);stimuli['extra']={};write_json(path,stimuli)
    with pytest.raises(ValueError,match='inputs changed'):record_response(session,first_response(session))
