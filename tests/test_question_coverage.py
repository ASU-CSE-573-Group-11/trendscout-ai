"""Checks prevent overstated coverage and duplicated aggregate commit series."""
import copy
import json

import pytest

from evaluation.question_coverage import ROOT, OUTPUT, build


def test_frozen_artifact_replays_and_preserves_all_companies():
    result = build()
    assert result == json.loads((ROOT / OUTPUT).read_text())
    assert len(result['questions']) == 28
    assert len(result['commit_calculations']) == 18
    assert result['commit_calculations']['sourcegraph']['first_four_total'] == 0
    assert result['commit_calculations']['sourcegraph']['last_four_total'] == 0
    assert result['commit_calculations']['crewai']['first_four_total'] == 90
    assert result['commit_calculations']['crewai']['last_four_total'] == 221
    assert result['summary']['family_counts']['github'] == 144


def test_components_do_not_become_full_answers_or_independent_origins():
    result = build()
    rows = {q['question_id']: q for q in result['questions']}
    assert rows['q-startups-multi-signal-ten-weeks']['coverage_status'] == 'partial_evidence'
    assert rows['q-funding-after-hiring']['coverage_status'] == 'partial_evidence'
    assert result['summary']['voice_articles'] == 5
    assert result['summary']['family_counts']['voice'] == 8
    assert len(result['summary']['voice_publishers']) == 2
    for q in result['questions']:
        assert q['limitation']
        assert 'gold_grade' not in q
    ids = [r['record_id'] for r in result['source_records']]
    assert len(ids) == len(set(ids))


def test_reordered_questions_require_explicit_review(tmp_path):
    # Fail before reading any source pack if specifications become misaligned.
    p = tmp_path / 'evaluation/real/questions.json'
    p.parent.mkdir(parents=True)
    obj = copy.deepcopy(json.loads((ROOT / 'evaluation/real/questions.json').read_text()))
    obj['questions'][0], obj['questions'][1] = obj['questions'][1], obj['questions'][0]
    p.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match='Question set changed'):
        build(tmp_path)
