import json
import pytest
from evaluation.ats_history import DIRECTORY, build, parse_board, parse_greenhouse


def test_twelve_company_coverage_replays_and_compares_identity_sets():
    r=build()
    assert r==json.loads((DIRECTORY/'review.json').read_text())
    assert r['summary']['historical_company_count']==12
    assert len(r['summary']['remaining_companies_without_comparable_history'])==6
    assert r['summary']['current_verified_ats_boards']==11
    e2b=next(c for c in r['comparisons'] if c['company_id']=='e2b')
    assert (e2b['baseline_listed'],e2b['latest_listed'])==(13,14)
    for c in r['comparisons']:
        assert c['net_posting_change']==len(c['newly_observed'])-len(c['no_longer_observed'])
        assert not set(c['newly_observed']) & set(c['retained'])


def test_rejects_js_shell_and_wrong_company():
    with pytest.raises(ValueError,match='embedded'):
        parse_board('<div id="root"></div>','E2B')
    html=(DIRECTORY/'sources/e2b-20261117065251.html').read_text()
    with pytest.raises(ValueError,match='company mismatch'):
        parse_board(html,'Different Employer')


def test_role_page_and_duplicate_ids_are_not_complete_board_evidence():
    data={'organization':{'name':'E2B'},'posting':{'id':'one'},'jobBoard':{'jobPostings':[]}}
    with pytest.raises(ValueError,match='complete board'):
        parse_board('window.__appData = '+json.dumps(data),'E2B')
    data['posting']=None;data['jobBoard']['jobPostings']=[{'id':'one','title':'Engineer'}]*2
    with pytest.raises(ValueError,match='duplicate'):
        parse_board('window.__appData = '+json.dumps(data),'E2B')


def test_greenhouse_source_count_and_company_specific_job_urls():
    h=(DIRECTORY/'sources/sourcegraph-20261004115737.html').read_text()
    assert len(parse_greenhouse(h,'sourcegraph91'))==10
    with pytest.raises(ValueError,match='Incomplete'):
        parse_greenhouse(h,'different-employer')
    with pytest.raises(ValueError,match='count header'):
        parse_greenhouse(h.replace('>10 jobs</h2>','>11 jobs</h2>'),'sourcegraph91')
