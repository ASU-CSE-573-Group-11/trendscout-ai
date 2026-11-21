"""Checks for historical coverage, source grounding, and annotation boundaries."""
import json
from datetime import datetime, timezone

from evaluation.collect_mixed_corpus import weekly_snapshots
from evaluation.integrate_mixed_round import component_judgment, extract
from evaluation.real_round import ROOT, frozen_records, source_reviewed_qrels


def test_mixed_round_preserves_questions_and_reconstructed_counts():
    directory=ROOT/'evaluation/mixed'
    records=frozen_records(directory)
    assert (directory/'questions.json').read_bytes()==(ROOT/'evaluation/questions.seed.json').read_bytes()
    assert {kind:sum(r['source_type']==kind for r in records)
            for kind in ['funding','job','github']}=={'funding':3,'job':18,'github':24}
    for record in records:
        if record['source_type']!='github':
            continue
        window=record['metadata']['activity_window']
        assert window['commit_count']==len(window['commits'])
        assert len({c['sha'] for c in window['commits']})==window['commit_count']
        start=datetime.fromisoformat(window['start'].replace('Z','+00:00'))
        end=datetime.fromisoformat(window['end'].replace('Z','+00:00'))
        assert (end-start).total_seconds()==7*86400
        assert end.weekday()==6 and end.hour==23
        assert all(start<datetime.fromisoformat(c['committed_at'].replace('Z','+00:00'))<=end
                   for c in window['commits'])
        assert record['metadata']['stargazers_count'] is None
        assert record['metadata']['open_issues_count'] is None


def test_weekly_partition_preserves_current_observation_and_boundary_commit():
    directory=ROOT/'evaluation/mixed'
    snapshot=json.loads((directory/'sources/langchain-commits.json').read_text())
    observed=snapshot['observed_at']
    records=list(weekly_snapshots(snapshot))
    assert len(records)==8
    assert {r['observed_at'] for r in records}=={observed}
    shas=[c['sha'] for r in records for c in r['metadata']['activity_window']['commits']]
    assert len(shas)==len(set(shas))


def test_extraction_offsets_are_exact_and_never_represent_agreement():
    records=frozen_records(ROOT/'evaluation/mixed')
    entities,relations=extract(records)
    by_id={r['record_id']:r for r in records}
    assert len(entities)>=200
    for entity in entities:
        assert by_id[entity['document_id']]['text'][entity['start']:entity['end']]==entity['entity_text']
        assert entity['review_status']=='pending'
    assert {r['label'] for r in relations}=={'MENTIONS'}


def test_component_rubric_does_not_turn_jobs_into_hiring_growth():
    records=frozen_records(ROOT/'evaluation/mixed')
    q={'question_id':'q-langchain-github-since-september'}
    for record in records:
        grade,quote,reason=component_judgment(q,record)
        assert grade in {0,1}
        if grade:
            assert quote in record['text'] and 'does not alone' in reason
    assert all(component_judgment({'question_id':'q-future-performance'},r)[0]==0 for r in records)


def test_all_component_judgments_are_traceable_and_agreement_remains_unclaimed():
    directory=ROOT/'evaluation/mixed'
    payload=source_reviewed_qrels(directory,directory/'integration/component-qrels.json')
    assert len(payload['judgments'])==1260
    assert payload['component_relevance_only'] and not payload['human_adjudicated']
    assert {r['grade'] for r in payload['judgments']}=={0,1}
    status=json.loads((directory/'integration/agreement-status.json').read_text())
    assert status['status']=='records_required' and status['cohen_kappa'] is None
