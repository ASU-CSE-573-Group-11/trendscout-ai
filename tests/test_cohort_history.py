import copy
import json
import shutil

import pytest

from evaluation.cohort_history import replay as replay_history
from evaluation.cohort_jobs import normalize, replay as replay_jobs
from evaluation.real_round import ROOT
from evaluation.sueda_completion import report


def test_all_cohort_histories_replay_without_historical_counters():
    directory=ROOT/'evaluation/cohort-history-v2'
    result=replay_history(directory)
    assert result['companies_collected']==result['companies_requested']==18
    assert result['weekly_records']==144
    records=[json.loads(line) for line in (directory/'records.jsonl').read_text().splitlines()]
    for cid in {r['company_id'] for r in records}:
        assert len([r for r in records if r['company_id']==cid])==8
    for r in records:
        assert all(r['metadata'][key] is None for key in
                   ['stargazers_count','forks_count','open_issues_count'])


def test_jobs_replay_and_missing_coverage_remains_unknown():
    directory=ROOT/'evaluation/cohort-job-history'
    result=replay_jobs(directory)
    assert result['current_boards']==9
    assert result['historical_companies']==2
    assert result['job_observations']==393
    m=json.loads((directory/'manifest.json').read_text())
    unknown=[c for c in m['companies'] if not c['boards']]
    assert unknown and all(c['current_listed'] is None for c in unknown)
    sourcegraph=next(c for c in m['companies'] if c['company_id']=='sourcegraph')
    assert not sourcegraph['historical_in_window']
    assert len(sourcegraph['boards'][0]['out_of_window_captures'])==2


@pytest.mark.parametrize('change',['id','duplicate','total','future'])
def test_job_normalization_rejects_incomplete_or_impossible_source(change):
    job={'id':1,'title':'Engineer','absolute_url':'https://job-boards.greenhouse.io/acme/jobs/1'}
    payload={'jobs':[job],'meta':{'total':1}}
    board={'type':'greenhouse'}
    if change=='id':
        del job['id']
    elif change=='duplicate':
        payload={'jobs':[job,copy.deepcopy(job)],'meta':{'total':2}}
    elif change=='total':
        payload['meta']['total']=2
    else:
        board={'type':'ashby'}
        job['publishedAt']='2099-01-01T00:00:00Z'
    with pytest.raises(ValueError):
        normalize(payload,{'company_id':'acme','name':'Acme'},board,
            'https://example.com/jobs','2026-11-21T00:00:00.123456Z','2026-11-21T00:00:00.123456Z')


def test_job_replay_rejects_changed_source(tmp_path):
    original=ROOT/'evaluation/cohort-job-history'
    directory=tmp_path/'jobs'
    shutil.copytree(original,directory)
    m=json.loads((directory/'manifest.json').read_text())
    path=directory/m['sources'][0]['file']
    path.write_text('{}')
    with pytest.raises(ValueError,match='source checksum'):
        replay_jobs(directory)


def test_completion_reports_real_unfilled_inputs_without_modifying_them():
    paths=[ROOT/'evaluation/real/pilot-session/responses.json',
           ROOT/'evaluation/real/workbooks/mehmet-attestation.json',
           ROOT/'evaluation/real/trust-pilot.json']
    before=[p.read_bytes() for p in paths]
    result=report()
    assert len(result['coverage'])==18
    assert result['pilot']['submitted_responses']==len(json.loads(before[0])['responses'])
    assert result['pilot']['scored_task_results']==len(json.loads(before[2])['task_results'])
    assert result['agreement']['cohen_kappa'] is None
    assert not result['complete_research_submission']
    assert before==[p.read_bytes() for p in paths]
