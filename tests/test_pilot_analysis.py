"""Example responses used here exist only in temporary test directories."""
import json
import shutil

import pytest

from evaluation.pilot_analysis import summarize
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


def record_first(directory,pid,duration,confidence):
    a=next(a for a in read_json(directory/'pilot-session/assignments.json')['assignments']
        if a['participant_id']==pid and a['order']==1)
    record_response(directory,{'participant_id':pid,'question_id':a['question_id'],
        'evidence_state':'insufficient','evidence_numbers':[],
        'action':'abstain','confidence':confidence,'duration_seconds':duration})


def test_no_responses_produce_no_measurements(session):
    report=summarize(session)
    assert report['submitted_tasks']==0 and report['remaining_tasks']==30
    assert report['observed_measurements']['duration_seconds'] is None
    assert report['accuracy'] is None and report['pilot_effect_estimate'] is None


def test_partial_actual_records_are_summarized_without_grading_or_changes(session):
    record_first(session,'P01',20,2)
    record_first(session,'P03',40,4)
    p=session/'pilot-session/responses.json';before=p.read_bytes()
    report=summarize(session)
    assert report['submitted_tasks']==2 and report['remaining_tasks']==28
    assert report['participants_complete']==0
    assert report['observed_measurements']['duration_seconds']['median']==30
    assert report['observed_measurements']['confidence']['mean']==3
    assert report['descriptive_only'] and report['accuracy'] is None
    assert sum(r['responses'] for r in report['by_condition'].values())==2
    assert before==p.read_bytes()


def test_complete_balanced_collection_has_descriptive_pairs_without_final_accuracy(session):
    assignments=read_json(session/'pilot-session/assignments.json')['assignments']
    for a in assignments:
        augmented=a['condition']=='citations_plus_state_and_path'
        record_response(session,{'participant_id':a['participant_id'],'question_id':a['question_id'],
            'evidence_state':'insufficient','evidence_numbers':[],
            'action':'abstain','confidence':4 if augmented else 2,
            'duration_seconds':40 if augmented else 20})
    report=summarize(session)
    assert report['collection_complete'] and report['submitted_tasks']==30
    assert report['participants_complete']==5 and report['remaining_tasks']==0
    paired=report['paired_condition_descriptives']
    assert paired['participants']==5 and paired['mean_duration_difference_seconds']==20
    assert paired['mean_confidence_difference']==2
    assert report['accuracy'] is None and report['pilot_effect_estimate'] is None


@pytest.mark.parametrize('change',['duplicate','stimulus','condition','duration'])
def test_invalid_submitted_record_is_rejected(session,change):
    record_first(session,'P01',20,2)
    p=session/'pilot-session/responses.json';data=read_json(p)
    if change=='duplicate':data['responses'].append(dict(data['responses'][0]))
    elif change=='stimulus':data['responses'][0]['stimulus_sha256']='changed'
    elif change=='condition':data['responses'][0]['condition']='not_assigned'
    else:data['responses'][0]['duration_seconds']=-1
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):summarize(session)
