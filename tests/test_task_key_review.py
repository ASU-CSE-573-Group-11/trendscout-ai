"""Review decisions here are test fixtures, never empirical review records."""
import json
import shutil

import pytest

from evaluation.real_round import ROOT, read_json
from evaluation.task_key_review import ReviewConsole, record_review, status


@pytest.fixture
def review_round(tmp_path):
    source=ROOT/'evaluation/real'
    for name in ['manifest.json','records.jsonl','trust-pilot.json']:
        shutil.copy(source/name,tmp_path/name)
    shutil.copytree(source/'sources',tmp_path/'sources')
    shutil.copytree(source/'pilot-session',tmp_path/'pilot-session')
    # Preserve actual source fixtures; any test review is confined to tmp_path.
    for name in ['task-key-second-review.json','task-key-adjudication.json','final-grading.json']:
        target=tmp_path/'pilot-session'/name
        if target.exists():target.unlink()
    (tmp_path/'sueda-review').mkdir()
    shutil.copy(source/'sueda-review/pilot-evidence-policy.md',tmp_path/'sueda-review/pilot-evidence-policy.md')
    return tmp_path


def decisions(directory):
    ids=read_json(directory/'pilot-session/protocol.json')['task_ids']
    return [{'question_id':qid,'expected_state':'insufficient',
        'accepted_actions':['abstain'],'source_basis':'frozen_corpus',
        'rationale':'Temporary test fixture source decision.'} for qid in ids]


def test_form_has_no_initial_key_or_participant_responses(review_round):
    console=ReviewConsole(review_round)
    text=console.home()
    assert text.count('<fieldset>')==6
    assert 'Your name' in text and 'Explain the source basis' in text
    assert 'expected_state' not in text and ' selected' not in text
    assert not (review_round/'pilot-session/task-key-second-review.json').exists()
    assert status(review_round)['recorded_decisions']==0


def test_actual_review_is_locked_without_changing_participant_responses(review_round):
    console=ReviewConsole(review_round)
    p=review_round/'pilot-session/responses.json';before=p.read_bytes()
    result=record_review(review_round,'Mehmet Aksit',decisions(review_round),True,console.fingerprints)
    assert result['recorded_decisions']==6
    assert not result['final_adjudication_complete']
    assert result['state_differences_from_initial_key'][0]['question_id']=='q-why-emerging'
    assert p.read_bytes()==before
    with pytest.raises(FileExistsError):
        record_review(review_round,'Mehmet Aksit',decisions(review_round),True,console.fingerprints)


@pytest.mark.parametrize('problem',['confirmation','missing','rationale','actions','source_change'])
def test_incomplete_or_changed_review_is_rejected(review_round,problem):
    console=ReviewConsole(review_round);entries=decisions(review_round);confirmed=True
    if problem=='confirmation':confirmed=False
    elif problem=='missing':entries.pop()
    elif problem=='rationale':entries[0]['rationale']=' '
    elif problem=='actions':entries[0]['accepted_actions']=[]
    else:
        p=review_round/'sueda-review/pilot-evidence-policy.md';p.write_text(p.read_text()+'\nChanged policy\n')
    with pytest.raises(ValueError):
        record_review(review_round,'Mehmet Aksit',entries,confirmed,console.fingerprints)
    assert not (review_round/'pilot-session/task-key-second-review.json').exists()
