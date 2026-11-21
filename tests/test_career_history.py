import json
import pytest
from collectors.browser_snapshot import validate_url
from evaluation.career_history import DIRECTORY, build, parse_roles


def test_retained_career_archives_replay_with_separate_talent_pool():
    report=build()
    assert report == json.loads((DIRECTORY/'review.json').read_text())
    assert report['summary']['new_historical_companies'] == 1
    for c in report['comparisons']:
        assert c['baseline_specific_roles']==8
        assert c['latest_specific_roles']==2
        assert c['net_posting_change']==-6
        assert len(c['newly_observed'])==1
        assert len(c['no_longer_observed'])==7
    assert all(s['talent_pool_entries']==1 for s in report['snapshots'])


def test_js_shell_is_unknown_and_duplicate_links_are_rejected():
    with pytest.raises(ValueError,match='coverage unknown'):
        parse_roles('llamaindex','<div>Loading jobs…</div>')
    anchor='<a href="/careers/engineer" aria-label="Engineer">Engineer</a>'
    with pytest.raises(ValueError,match='Duplicate'):
        parse_roles('llamaindex','<ul class="RoleList">'+anchor*2+'</ul>')


@pytest.mark.parametrize('url',[
    'https://web.archive.org/web/20261001/https://llamaindex.ai/careers',
    'https://llamaindex.ai.evil.example/careers',
    'https://llamaindex.ai@evil.example/careers',
    'http://llamaindex.ai/careers',
])
def test_current_browser_capture_rejects_archives_and_foreign_hosts(url):
    with pytest.raises(ValueError):validate_url(url,'llamaindex.ai')


def test_official_company_subdomain_is_allowed():
    validate_url('https://www.llamaindex.ai/careers','llamaindex.ai')
