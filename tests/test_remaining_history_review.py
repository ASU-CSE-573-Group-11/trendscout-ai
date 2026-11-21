import json
import pytest
from evaluation.remaining_history_review import ROOT, DIRECTORY, build, parse_chroma, yc_page, branded_titles, compare
from collectors.archive_browser import validate_capture


def test_final_six_review_replays_without_conflating_populations():
    r=build()
    assert r==json.loads((DIRECTORY/'review.json').read_text())
    assert r['summary']['complete_official_population_history_count']==15
    assert set(r['summary']['companies_without_complete_official_population_history'])=={'crewai','replicate','wandb'}
    assert r['summary']['companies_with_any_paired_public_channel']==17
    assert r['summary']['company_without_paired_historical_population']==['crewai']
    assert 'continue' in r['summary']['complete_official_population_history_companies']
    assert 'langfuse' in r['summary']['complete_official_population_history_companies']
    assert r['crewai_current_board']['listed_count']==4
    assert len(r['crewai_historical_advertisements'])==2
    assert all(a['active_at_archive_capture'] is None and not a['complete_historical_board'] for a in r['crewai_historical_advertisements'])
    # Parent brand-title channel remains separate from complete Ashby board history.
    lf_parent=[c for c in r['comparisons'] if c['company_id']=='langfuse' and c['population']=='explicit_brand_titles_in_parent_ats']
    assert lf_parent
    assert all(s['parent_board_count']>s['listed_count'] for s in r['snapshots']['langfuse'] if s['population']=='explicit_brand_titles_in_parent_ats')
    cont=[c for c in r['comparisons'] if c['company_id']=='continue' and c['population']=='complete_official_ats_board']
    assert cont and cont[0]['baseline_listed']==3 and cont[0]['latest_listed']==3


def test_js_shell_or_inconsistent_category_counts_are_not_zero_jobs():
    with pytest.raises(ValueError,match='complete listing'):
        parse_chroma('<div>Loading jobs</div>')
    with pytest.raises(ValueError,match='category totals'):
        parse_chroma('<h2>Engineering (2 roles)</h2><a href="/careers/engineer">Engineer</a>')


def test_directory_empty_array_excludes_related_jobs_and_requires_identity():
    data={'component':'WaasShowJobsPage','props':{'company':{'name':'Continue','website':'https://continue.dev','id':28957,'slug':'continue'},'jobPostings':[],'relatedJobs':[{'id':1,'title':'Unrelated employer role'}]}}
    html='<div data-page=\''+json.dumps(data)+'\'></div>'
    rows,_=yc_page(html,'Continue','continue.dev')
    assert rows==[]
    with pytest.raises(ValueError,match='mismatch'):
        yc_page(html,'Continue','different.example')
    data['component']='WaasShowJobPage'
    with pytest.raises(ValueError,match='complete employer job-list'):
        yc_page('<div data-page=\''+json.dumps(data)+'\'></div>','Continue','continue.dev')


def test_brand_subset_does_not_take_parent_or_substring_roles():
    rows=[{'posting_id':'one','title':'Backend Engineer - Weights & Biases'},
          {'posting_id':'two','title':'CoreWeave generic engineer'},
          {'posting_id':'three','title':'Replicated storage engineer'},
          {'posting_id':'four','title':'Replicate engineer'}]
    assert [r['posting_id'] for r in branded_titles(rows,'wandb')]==['one']
    assert [r['posting_id'] for r in branded_titles(rows,'replicate')]==['four']


def test_rename_into_brand_subset_is_not_new_parent_posting():
    old={'company_id':'langfuse','population':'brand','snapshot_at':'2026-10-01','listings':[], 'parent_posting_ids':['existing']}
    new={'population':'brand','snapshot_at':'2026-11-21','listings':[{'posting_id':'existing','title':'Langfuse engineer'}]}
    r=compare(old,new)
    assert r['newly_selected_ids_already_in_parent_baseline']==['existing']
    assert r['newly_selected_ids_absent_from_parent_baseline']==[]
    new['population']='whole parent'
    with pytest.raises(ValueError,match='Incomparable'):
        compare(old,new)


def test_archive_capture_must_match_exact_clock_host_and_timezone():
    url='https://web.archive.org/web/20261102064608id_/https://www.trychroma.com/careers'
    headers={'Memento-Datetime':'Mon, 02 Nov 2026 06:46:08 GMT'}
    assert validate_capture('20261102064608',headers,url)=='2026-11-02T06:46:08Z'
    with pytest.raises(ValueError):validate_capture('20261103064608',headers,url)
    with pytest.raises(ValueError):validate_capture('20261102064608',headers,'https://www.trychroma.com/careers')
    with pytest.raises(ValueError,match='timezone'):validate_capture('20261102064608',{'Memento-Datetime':'02 Nov 2026 06:46:08'},url)
