"""Check configured cohort YC profile links and replay the evidence offline.

Checks name/domain support at observation time. A missing page does not prove
that a company never attended YC, and directory identity is not a trend signal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlsplit

import requests

from collectors.records import utc_now
from collectors.common import plain_text
from evaluation.real_round import ROOT


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def host(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.')


class ProfileHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title=False;self.title=[];self.links=[]
        self.title_done=False

    def handle_starttag(self,tag,attrs):
        if tag=='title' and not self.title_done:self.in_title=True
        if tag=='a':
            href=dict(attrs).get('href')
            if href:self.links.append(href)

    def handle_endtag(self,tag):
        if tag=='title' and self.in_title:
            self.in_title=False;self.title_done=True

    def handle_data(self,text):
        if self.in_title:self.title.append(text)


def classify(company,source,body):
    result={**source}
    if source.get('http_status')!=200:
        result['verification_status']='profile_not_found' if source.get('http_status')==404 else 'source_unavailable'
        result['identity_supported']=False
        return result
    parsed=ProfileHTML();parsed.feed(body)
    title=' '.join(' '.join(parsed.title).split())
    names=[company['name'],*company.get('aliases',[])]
    name_match=any(re.search(r'(?<!\w)'+re.escape(n)+r'(?!\w)',title,re.I) for n in names)
    domain=company['domain'].lower().removeprefix('www.')
    links=sorted({urljoin(source['response_url'],link) for link in parsed.links
                  if host(urljoin(source['response_url'],link))==domain})
    response=urlsplit(source['response_url'])
    is_profile=host(source['response_url'])=='ycombinator.com' and response.path.startswith('/companies/')
    supported=bool(name_match and links and is_profile)
    result.update(page_title=title,name_supported_by_title=bool(name_match),
        matching_official_domain_links=links,identity_supported=supported,
        verification_status='current_profile_supported' if supported else 'profile_needs_review')
    return result


def collect(out):
    if out.exists():raise ValueError('Refusing to overwrite identity evidence')
    out.mkdir(parents=True);(out/'sources').mkdir()
    original=ROOT/'data/registry/cohort.json'
    (out/'cohort.json').write_bytes(original.read_bytes())
    companies=[c for c in json.loads(original.read_text())['companies'] if c['status']=='included']

    def fetch(company):
        url=company.get('yc_url')
        base={'company_id':company['company_id'],'name':company['name'],'official_domain':company['domain'],
            'registry_yc_url':url,'checked_at':utc_now()}
        if not url:
            return {**base,'verification_status':'no_yc_assertion_configured','identity_supported':False}
        if host(url)!='ycombinator.com' or not urlsplit(url).path.startswith('/companies/'):
            raise ValueError('Configured URL is not a YC company profile')
        try:
            response=requests.get(url,timeout=25,headers={'User-Agent':'TrendScout-research/1.0'})
            filename='sources/'+company['company_id']+'.html'
            (out/filename).write_bytes(response.content)
            base.update(response_url=response.url,http_status=response.status_code,
                file=filename,sha256=sha(out/filename))
            result=classify(company,base,response.content.decode('utf-8',errors='replace'))
        except requests.RequestException as exc:
            result={**base,'verification_status':'source_unavailable','identity_supported':False,'error_type':type(exc).__name__}
        print(company['company_id'],result['verification_status'],flush=True)
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        checks=list(executor.map(fetch,companies))
    report={'status':'configured_profile_check_complete','cohort_sha256':sha(out/'cohort.json'),
        'companies':checks,'counts':dict(Counter(r['verification_status'] for r in checks)),
        'verification_rule':'Current YC company-profile response is HTTP 200, title contains a frozen company name/alias, and a page link has the exact frozen official domain.',
        'scope':'Current directory source check. Frozen cohort membership, registry assertions and prior experiments are unchanged.',
        'limits':['HTTP 404 or unavailable access is not proof of non-membership in YC.',
            'No YC batch, funding event, hiring fact, incorporation identity or historical profile presence is inferred.',
            'Companies without a configured YC URL carry no verified or rejected YC membership claim.',
            'Name/domain support is a reproducible source check, not independent personal annotation.']}
    (out/'manifest.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return replay(out)


def replay(out):
    report=json.loads((out/'manifest.json').read_text())
    if sha(out/'cohort.json')!=report['cohort_sha256']:
        raise ValueError('Identity cohort checksum mismatch')
    companies=[c for c in json.loads((out/'cohort.json').read_text())['companies'] if c['status']=='included']
    checks=report['companies']
    if [r['company_id'] for r in checks]!=[c['company_id'] for c in companies]:
        raise ValueError('Incomplete identity-check cohort accounting')
    for company,row in zip(companies,checks):
        if row['name']!=company['name'] or row['official_domain']!=company['domain'] or row['registry_yc_url']!=company.get('yc_url'):
            raise ValueError('Identity-check registry fields changed')
        if row.get('file'):
            path=out/row['file']
            if sha(path)!=row['sha256']:raise ValueError('Identity page checksum mismatch')
            derived={'page_title','name_supported_by_title','matching_official_domain_links','identity_supported','verification_status'}
            source={k:v for k,v in row.items() if k not in derived}
            rebuilt=classify(company,source,path.read_bytes().decode('utf-8',errors='replace'))
            if rebuilt!=row:raise ValueError('Identity page replay differs from saved check')
        elif not company.get('yc_url'):
            if row['verification_status']!='no_yc_assertion_configured' or row['identity_supported']:
                raise ValueError('Missing URL cannot establish a YC identity')
        elif row['verification_status']!='source_unavailable' or row['identity_supported']:
            raise ValueError('Unavailable source cannot establish identity')
    counts=dict(Counter(r['verification_status'] for r in checks))
    if counts!=report['counts']:raise ValueError('Identity-check summary mismatch')
    if report.get('overlay_sha256'):
        if sha(out/'usable-profiles.json')!=report['overlay_sha256'] or sha(out/'source-review-decisions.json')!=report['source_review_sha256']:
            raise ValueError('Identity overlay checksum mismatch')
        decisions=json.loads((out/'source-review-decisions.json').read_text())
        if report.get('source_reviewed_mismatches')!=len(decisions['decisions']):
            raise ValueError('Identity mismatch summary count changed')
        if overlay(out,report,decisions)!=json.loads((out/'usable-profiles.json').read_text()):
            raise ValueError('Identity overlay differs from source checks')
    return {'status':'offline_replay_verified','companies_accounted_for':len(checks),
        'configured_urls_checked':sum(bool(c.get('yc_url')) for c in companies),
        'counts':counts,'usable_yc_profiles':sum(r['identity_supported'] for r in checks),
        'source_reviewed_mismatches':report.get('source_reviewed_mismatches',0)}


def overlay(out,report,decisions):
    by_id={r['company_id']:r for r in report['companies']}
    rejected={}
    for decision in decisions['decisions']:
        cid=decision['company_id'];row=by_id[cid]
        if cid in rejected or decision['decision']!='exclude_mismatched_profile':
            raise ValueError('Invalid or duplicate source-review decision')
        if decision['source_sha256']!=row.get('sha256') or row['verification_status']!='profile_needs_review':
            raise ValueError('Mismatch decision is not bound to a fetched review candidate')
        text=plain_text((out/row['file']).read_text())
        passages=decision.get('source_passages')
        if not isinstance(passages,list) or not passages or any(not isinstance(q,str) or not q.strip() for q in passages):
            raise ValueError('Mismatch decision needs nonempty source passages')
        if not decision['reason'].strip() or any(quote not in text for quote in passages):
            raise ValueError('Mismatch decision lacks exact source support')
        rejected[cid]=decision
    rows=[]
    for row in report['companies']:
        cid=row['company_id'];usable=row['identity_supported'] and cid not in rejected
        disposition=('exclude_mismatched_profile' if cid in rejected else 'use_current_profile' if usable
                     else 'no_membership_assertion' if not row['registry_yc_url'] else 'unavailable_or_unverified_profile')
        rows.append({'company_id':cid,'name':row['name'],'official_domain':row['official_domain'],
            'frozen_registry_yc_url':row['registry_yc_url'],
            'usable_yc_url':row['registry_yc_url'] if usable else None,
            'disposition':disposition,'observed_at':row['checked_at'],
            'source_sha256':row.get('sha256'),
            'reason':rejected[cid]['reason'] if cid in rejected else row['verification_status']})
    return {'scope':'Current usable YC identity evidence; does not change cohort membership or earlier frozen assertions.',
        'cohort_sha256':report['cohort_sha256'],'companies':rows,
        'counts':dict(Counter(r['disposition'] for r in rows))}


def write_overlay(out):
    report=json.loads((out/'manifest.json').read_text())
    decisions=json.loads((out/'source-review-decisions.json').read_text())
    result=overlay(out,report,decisions)
    (out/'usable-profiles.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    report.update(overlay_sha256=sha(out/'usable-profiles.json'),
        source_review_sha256=sha(out/'source-review-decisions.json'),
        source_reviewed_mismatches=len(decisions['decisions']))
    (out/'manifest.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return replay(out)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['collect','replay','overlay'])
    parser.add_argument('--out',type=Path,default=ROOT/'evaluation/cohort-identity-review')
    args=parser.parse_args()
    print(json.dumps({'collect':collect,'replay':replay,'overlay':write_overlay}[args.action](args.out),indent=2))
