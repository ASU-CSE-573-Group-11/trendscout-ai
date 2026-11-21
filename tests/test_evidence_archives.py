import copy
import json

import pytest

from collectors.evidence_archives import replay
from evaluation.real_round import ROOT
from signals.adapters import AdapterError, job_observation
from signals.pipeline import run_trend_pipeline


DIRECTORY = ROOT / 'evaluation/sueda-evidence-extension'


def observations():
    return [json.loads(line) for line in
            (DIRECTORY / 'job-observations.jsonl').read_text().splitlines()]


def test_frozen_extension_replays_offline():
    result = replay(DIRECTORY)
    assert result['public_voice_documents'] == 5
    assert result['public_voice_associations'] == 8
    assert result['job_observations'] == 206
    assert result['net_posting_change'] == -2


def test_archive_clock_preserves_retrieval_and_missing_weeks():
    records = observations()
    original = copy.deepcopy(records[0])
    observation = job_observation(records[0])
    assert observation.observed_at.isoformat().startswith('2026-10-21')
    assert records[0] == original
    assert records[0]['observed_at'] > records[0]['metadata']['source_snapshot_at']
    run = run_trend_pipeline(records)
    assert [s.as_dict() for s in run.bundle.series] == json.loads(
        (DIRECTORY / 'signals/series.json').read_text())
    assert run.coverage == json.loads((DIRECTORY / 'signals/coverage.json').read_text())
    series = run.bundle.find('jobs:open_postings|company=langchain')
    assert [p.value for p in series.points] == [104, None, None, None, 102]
    assert set(run.labels()) == {'insufficient_history'}


@pytest.mark.parametrize('change', ['unverified', 'future', 'hash'])
def test_archive_clock_rejects_unsupported_backdating(change):
    record = observations()[0]
    if change == 'unverified':
        record['metadata']['archive_capture']['verified'] = False
    elif change == 'future':
        record['metadata']['source_snapshot_at'] = '2099-01-01T00:00:00Z'
    else:
        record['metadata']['archive_capture']['payload_sha256'] = 'invalid'
    with pytest.raises(AdapterError):
        job_observation(record)
