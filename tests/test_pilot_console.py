"""All example answers and timer values are confined to temporary fixtures."""
import shutil

import pytest

from evaluation.pilot_console import PilotConsole, task_page, receipt_page
from evaluation.pilot_session import prepare
from evaluation.real_round import ROOT, read_json, write_json


@pytest.fixture
def console(tmp_path):
    source=ROOT/'evaluation/real'
    shutil.copy(source/'trust-pilot.json',tmp_path/'trust-pilot.json')
    pilot=read_json(tmp_path/'trust-pilot.json');pilot['task_results']=[]
    write_json(tmp_path/'trust-pilot.json',pilot)
    (tmp_path/'answers').mkdir()
    shutil.copy(source/'answers/hybrid.jsonl.gz',tmp_path/'answers/hybrid.jsonl.gz')
    prepare(tmp_path)
    clock=[100.0]
    return PilotConsole(tmp_path,clock=lambda:clock[0]),clock


def response():
    return {'evidence_state':'insufficient','evidence_numbers':[],
            'action':'abstain','confidence':3}


def test_start_does_not_create_a_response_and_preserves_frozen_order(console):
    app,_=console
    token,assignment,stimulus=app.start('P05')
    assert assignment['order']==1
    assert read_json(app.directory/'pilot-session/responses.json')['responses']==[]
    text=task_page(token,assignment,stimulus)
    assert '<html lang="en">' in text and 'name="confidence"' in text
    assert 'expected_state' not in text and ' selected' not in text
    with pytest.raises(ValueError,match='already has an open task'):
        app.start('P05')


def test_timer_records_elapsed_submission_without_inventing_correctness(console):
    app,clock=console
    token,_,_=app.start('P05')
    clock[0]+=37.25
    app.submit(token,response())
    saved=read_json(app.directory/'pilot-session/responses.json')['responses'][0]
    assert saved['duration_seconds']==37.25
    assert saved['timing_method']=='server_monotonic_elapsed'
    assert not {'status_correct','evidence_correct','abstention_correct'} & saved.keys()
    assert read_json(app.directory/'trust-pilot.json')['task_results']==[]
    with pytest.raises(ValueError,match='already submitted'):
        app.submit(token,response())
    _,assignment,_=app.start('P05')
    assert assignment['order']==2


def test_invalid_response_is_not_saved_and_can_be_corrected(console):
    app,clock=console
    token,_,_=app.start('P05')
    clock[0]+=3
    with pytest.raises(ValueError,match='confidence'):
        app.submit(token,{**response(),'confidence':True})
    assert read_json(app.directory/'pilot-session/responses.json')['responses']==[]
    clock[0]+=7
    app.submit(token,response())
    assert read_json(app.directory/'pilot-session/responses.json')['responses'][0]['duration_seconds']==10


def test_unknown_participant_cannot_start(console):
    app,_=console
    with pytest.raises(ValueError,match='consent'):
        app.start('P99')


def test_receipt_distinguishes_one_answer_from_all_six_tasks(console):
    app,clock=console
    token,_,_=app.start('P05');clock[0]+=10;app.submit(token,response())
    receipt=receipt_page(app,'P05')
    assert '1 of 6 tasks saved' in receipt and '5 tasks remain' in receipt
    assert 'name="participant_id" value="P05"' in receipt
    assert 'completed all your assigned tasks' not in receipt
