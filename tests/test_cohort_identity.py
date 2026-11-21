import json
import shutil

import pytest

from evaluation.cohort_identity import classify,replay
from evaluation.real_round import ROOT


COMPANY={'company_id':'modal','name':'Modal','aliases':['Modal Labs'],'domain':'modal.com'}
SOURCE={'response_url':'https://www.ycombinator.com/companies/modal','http_status':200}


def test_current_identity_requires_both_name_and_exact_domain():
    matching='<head><title>Modal: compute | Y Combinator</title></head><a href="https://www.modal.com/">Website</a>'
    assert classify(COMPANY,SOURCE,matching)['identity_supported']
    wrong_company='<head><title>Modal: auto commerce | Y Combinator</title></head><a href="https://modalup.com/">Website</a>'
    assert not classify(COMPANY,SOURCE,wrong_company)['identity_supported']
    lookalike=matching.replace('www.modal.com','modal.com.example.org')
    assert not classify(COMPANY,SOURCE,lookalike)['identity_supported']


def test_later_svg_titles_cannot_create_a_company_name_match():
    body='<head><title>Different Company | Y Combinator</title></head><svg><title>Modal</title></svg><a href="https://modal.com">Related link</a>'
    result=classify(COMPANY,SOURCE,body)
    assert result['page_title']=='Different Company | Y Combinator'
    assert not result['identity_supported']


def test_missing_page_is_unverified_not_a_non_membership_claim():
    result=classify(COMPANY,{**SOURCE,'http_status':404},'Not found')
    assert result['verification_status']=='profile_not_found'
    assert result['identity_supported'] is False
    assert 'yc_member' not in result


def test_frozen_identity_audit_and_safe_overlay_replay():
    directory=ROOT/'evaluation/cohort-identity-review'
    result=replay(directory)
    assert result['companies_accounted_for']==18 and result['configured_urls_checked']==11
    assert result['usable_yc_profiles']==3 and result['source_reviewed_mismatches']==1
    overlay=json.loads((directory/'usable-profiles.json').read_text())
    modal=next(r for r in overlay['companies'] if r['company_id']=='modal')
    assert modal['usable_yc_url'] is None and modal['disposition']=='exclude_mismatched_profile'
    assert {r['company_id'] for r in overlay['companies'] if r['usable_yc_url']}=={'langfuse','continue','replicate'}


@pytest.mark.parametrize('file',['sources/modal.html','usable-profiles.json'])
def test_changed_source_or_overlay_cannot_pass_replay(tmp_path,file):
    shutil.copytree(ROOT/'evaluation/cohort-identity-review',tmp_path/'review')
    target=tmp_path/'review'/file;target.write_text('changed')
    with pytest.raises(ValueError,match='checksum'):
        replay(tmp_path/'review')
