"""Offline review of the final six companies, with explicit population boundaries."""
import argparse
from collections import Counter
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from collectors.archive_browser import validate_capture
from evaluation.ats_history import parse_board

ROOT=Path(__file__).resolve().parents[1]
DIRECTORY=ROOT/'evaluation/remaining-history-discovery'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class CareerList(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.current=None;self.parts=[];self.heading=None;self.heading_parts=[];self.headings=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='h2':self.heading=True;self.heading_parts=[]
        if tag=='a':
            u=urlsplit(a.get('href',''))
            if not u.netloc and re.fullmatch(r'/careers/[a-z0-9-]+',u.path) and not u.query:
                self.current=u.path;self.parts=[]
    def handle_data(self,text):
        if self.current:self.parts.append(text)
        if self.heading:self.heading_parts.append(text)
    def handle_endtag(self,tag):
        if tag=='a' and self.current:
            self.links.append({'posting_id':self.current,'title':''.join(self.parts).strip()});self.current=None
        if tag=='h2' and self.heading:
            self.headings.append(''.join(self.heading_parts));self.heading=False


def parse_chroma(html):
    p=CareerList();p.feed(html)
    counts=[int(m.group(1)) for text in p.headings for m in re.finditer(r'\((\d+)\s+roles?\)',text)]
    if not counts or sum(counts)!=len(p.links) or any(not r['title'] for r in p.links):
        raise ValueError('Career category totals do not establish a complete listing population')
    return unique_rows(p.links)


class Inertia(HTMLParser):
    def __init__(self):super().__init__();self.pages=[]
    def handle_starttag(self,tag,attrs):
        value=dict(attrs).get('data-page')
        if value:self.pages.append(json.loads(value))


def yc_page(html,company,domain,require_list=True):
    p=Inertia();p.feed(html)
    if len(p.pages)!=1:raise ValueError('Exactly one YC employer page payload required')
    data=p.pages[0];props=data['props'];employer=props['company']
    host=urlsplit(employer.get('website','')).hostname or ''
    if employer.get('name','').casefold()!=company.casefold() or host.removeprefix('www.')!=domain:
        raise ValueError('YC employer name/domain mismatch')
    if not require_list:return props
    if data['component']!='WaasShowJobsPage' or not isinstance(props.get('jobPostings'),list):
        raise ValueError('A complete employer job-list payload is required, not an individual or related-jobs page')
    jobs=props['jobPostings']
    if any(not j.get('title') or not j.get('companyUrl','').rstrip('/').endswith('/'+employer['slug']) for j in jobs):
        raise ValueError('YC listing does not belong to this employer')
    rows=unique_rows([{'posting_id':str(j['id']),'title':j['title']} for j in jobs])
    return rows,{'directory_company_id':employer['id'],'source_reported_company_status':employer.get('ycdc_status')}


def unique_rows(rows):
    if any(not isinstance(r.get('posting_id'),str) or not r['posting_id'] or not r.get('title') for r in rows):raise ValueError('Missing listing identity/title')
    if len({r['posting_id'] for r in rows})!=len(rows):raise ValueError('Duplicate listing identity')
    return sorted(rows,key=lambda r:r['posting_id'])


def greenhouse(payload):
    jobs=payload.get('jobs')
    if not isinstance(jobs,list) or payload.get('meta',{}).get('total',len(jobs))!=len(jobs):raise ValueError('Incomplete parent ATS job population')
    return unique_rows([{'posting_id':str(j['id']),'title':j['title']} for j in jobs])


def branded_titles(rows,brand):
    pattern=r'\blangfuse\b' if brand=='langfuse' else r'\bweights\s*(?:&|and)\s*biases\b' if brand=='wandb' else r'\breplicate\b'
    return [r for r in rows if re.search(pattern,unescape(r['title']),re.I)]


def compare(before,after):
    if before['population']!=after['population']:raise ValueError('Incomparable listing populations')
    a={r['posting_id'] for r in before['listings']};b={r['posting_id'] for r in after['listings']}
    result={'company_id':before['company_id'],'population':before['population'],'baseline_at':before['snapshot_at'],
            'latest_at':after['snapshot_at'],'baseline_listed':len(a),'latest_listed':len(b),'net_posting_change':len(b)-len(a),
            'newly_observed':sorted(b-a),'no_longer_observed':sorted(a-b),'retained':sorted(a&b)}
    if 'parent_posting_ids' in before:
        parent_before=set(before['parent_posting_ids'])
        result['newly_selected_ids_already_in_parent_baseline']=sorted((b-a)&parent_before)
        result['newly_selected_ids_absent_from_parent_baseline']=sorted((b-a)-parent_before)
    return result


class Meta(HTMLParser):
    def __init__(self):super().__init__();self.values={}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta' and a.get('property') in {'og:title','og:description'}:self.values[a['property']]=a.get('content','')


class Store:
    def __init__(self,root,directory):self.root=root;self.directory=directory;self.inputs={}
    def read(self,path):
        path=path.resolve();self.inputs[str(path.relative_to(self.root))]=sha(path);return path.read_text()
    def load(self,path):return json.loads(self.read(path))
    def catalog(self,name):
        result=self.load(self.directory/name)
        if isinstance(result,list):
            for source in result:
                if source.get('file') and source.get('sha256'):
                    p=self.directory/source['file'];self.read(p)
                    if sha(p)!=source['sha256']:raise ValueError('Retained source checksum mismatch')
        return result
    def source(self,source):
        status=source.get('http_status',source.get('status'))
        if status is not None and status!=200:raise ValueError('A failed HTTP retrieval is not a listing observation')
        p=self.directory/source['file'];text=self.read(p)
        if sha(p)!=source['sha256']:raise ValueError('Retained source changed')
        return text,str(p.relative_to(self.root))


def build(root=ROOT):
    directory=root/'evaluation/remaining-history-discovery';s=Store(root,directory)
    baseline=s.load(root/'evaluation/cohort-ats-history/review.json')
    old_companies=set(baseline['summary']['historical_companies'])
    discovery=s.catalog('discovery.json');archive_search=s.catalog('archive-discovery.json');archives=s.catalog('archive-captures.json')
    parent_discovery=s.catalog('parent-board-discovery.json');extra=s.catalog('extra-archive-captures.json')
    parent_apis=s.catalog('additional-endpoints.json');wandb_archives=s.catalog('coreweave-archive-captures.json');last_search=s.catalog('last-archive-search.json')
    replicate_discovery=s.catalog('replicate-yc-discovery.json');replicate_archives=s.catalog('replicate-yc-captures.json')
    wandb_discovery=s.catalog('wandb-discovery.json');s.catalog('parent-archive-discovery.json');render=s.load(directory/'langfuse-render.json')
    langfuse_ashby_discovery=s.catalog('langfuse-ashby-discovery.json');langfuse_ashby_archives=s.catalog('langfuse-ashby-captures.json')
    continue_ashby_discovery=s.catalog('continue-ashby-discovery.json');continue_ashby_archives=s.catalog('continue-ashby-captures.json')
    render_text,_=s.source(render)
    if 'https://api.ashbyhq.com/posting-api/job-board/clickhouse' not in render['job_data_urls']:
        raise ValueError('Official Langfuse-linked parent data endpoint not verified')
    lf_original=root/'evaluation/cohort-history-followup/sources/langfuse-careers.html'
    if 'https://clickhouse.com/company/careers?search=langfuse' not in s.read(lf_original):raise ValueError('Langfuse parent link missing')
    wb_original=root/'evaluation/cohort-history-followup/sources/wandb-careers.html'
    if 'coreweave.com/careers/weights-biases' not in s.read(wb_original):raise ValueError('Weights & Biases parent link missing')
    wb_page=next(x for x in discovery if x['source_id']=='wandb-parent');wb_html,_=s.source(wb_page)
    if "board: 'coreweave'" not in wb_html:raise ValueError('Parent ATS account not supported by official source')
    old_workable=s.load(root/'evaluation/cohort-archive-followup/manifest.json')
    official=next(x for x in old_workable['additional_mapping_sources'] if 'crewai-home' in x.get('file',''))
    homepage=root/'evaluation/cohort-archive-followup'/official['file']
    if sha(homepage)!=official['sha256'] or 'https://apply.workable.com/crewai/' not in s.read(homepage):raise ValueError('CrewAI official ATS mapping missing')
    identity=s.load(root/'evaluation/cohort-identity-review/usable-profiles.json')
    for cid in ['continue','replicate']:
        c=next(c for c in identity['companies'] if c['company_id']==cid)
        if not c.get('usable_yc_url'):raise ValueError('Employer-directory identity not supported')
    pools={'chroma':[],'continue':[],'langfuse':[],'wandb':[],'replicate':[]}
    def snapshot(cid,population,source,rows,path,archived=False,**more):
        record={'company_id':cid,'population':population,'snapshot_at':source.get('snapshot_at',source['observed_at']),
                'observed_at':source['observed_at'],'archived':archived,'source_file':path,
                'source_url':source.get('response_url') or source.get('url'),'listed_count':len(rows),'listings':rows,**more}
        pools[cid].append(record)
    def verified(source,catalog):
        matches=[c for row in catalog for c in row.get('captures',[]) if c['timestamp']==source['timestamp'] and c['original']==source['original_url']]
        if not matches or source.get('capture_verified') is not True:raise ValueError('Archive missing verified CDX binding')
        if not '20251101000000'<=source['timestamp']<='20261121235959':raise ValueError('Archive outside study window')
        when=validate_capture(source['timestamp'],{'Memento-Datetime':source['memento_datetime']},source['response_url'])
        if when!=source['snapshot_at']:raise ValueError('Archived source clock mismatch')
        return s.source(source)
    # Chroma: whole native list, category totals checked at every retained time.
    browser=root/'evaluation/browser-observations/chroma-2026-11-21';bm=s.load(browser/'manifest.json');html=s.read(browser/'rendered.html')
    if sha(browser/'rendered.html')!=bm['sha256']:raise ValueError('Current Chroma DOM changed')
    snapshot('chroma','complete_official_career_list',bm,parse_chroma(html),str((browser/'rendered.html').relative_to(root)))
    original_search=s.load(root/'evaluation/cohort-history-followup/archive-search.json')
    for stamp in ['20261003182939','20261102064608']:
        d=root/'evaluation/browser-archives'/('chroma-'+stamp);m=s.load(d/'manifest.json');body=s.read(d/m['file'])
        if m['status']!='archive_clock_verified' or m.get('scripts_disabled') is not True or sha(d/m['file'])!=m['sha256']:raise ValueError('Historical browser payload not verified')
        if not any(c['timestamp']==stamp and c['original']==m['original_url'] for row in original_search if row['company_id']=='chroma' for c in row['captures']):raise ValueError('Chroma capture absent from retained CDX')
        if validate_capture(stamp,{'Memento-Datetime':m['memento_datetime']},m['response_url'])!=m['snapshot_at']:raise ValueError('Chroma archive clock changed')
        snapshot('chroma','complete_official_career_list',m,parse_chroma(body),str((d/m['file']).relative_to(root)),True)
    # Directory channels: explicit zero means zero listings here, not zero company hiring.
    for cid,company,domain in [('continue','Continue','continue.dev'),('replicate','Replicate','replicate.com')]:
        src=next(x for x in discovery if x['source_id']=='continue-yc') if cid=='continue' else next(x for x in replicate_discovery if x['source_id']=='replicate-yc')
        html,path=s.source(src);rows,meta=yc_page(html,company,domain)
        snapshot(cid,'yc_employer_directory_channel',src,rows,path,directory_metadata=meta)
        for source in archives+replicate_archives:
            if source['source_id']!=cid+'-yc' or source.get('error'):continue
            html,path=verified(source,archive_search if cid=='continue' else replicate_discovery);rows,meta=yc_page(html,company,domain)
            snapshot(cid,'yc_employer_directory_channel',source,rows,path,True,directory_metadata=meta)
    # Parent accounts: exact brand-name title matches only; company total never substituted.
    current=next(x for x in parent_discovery if x['source_id']=='clickhouse-ashby-api');text,path=s.source(current);payload=json.loads(text)
    if not isinstance(payload.get('jobs'),list):raise ValueError('Missing parent Ashby public job array')
    rows=unique_rows([{'posting_id':j['id'],'title':j['title']} for j in payload['jobs'] if j.get('isListed',True)])
    snapshot('langfuse','explicit_brand_titles_in_parent_ats',current,branded_titles(rows,'langfuse'),path,parent='ClickHouse',parent_board_count=len(rows),parent_posting_ids=[r['posting_id'] for r in rows],title_filter='whole word Langfuse')
    for source in extra:
        if source['source_id']!='langfuse-parent-board' or source.get('error'):continue
        html,path=verified(source,parent_discovery);rows=parse_board(html,'ClickHouse')
        snapshot('langfuse','explicit_brand_titles_in_parent_ats',source,branded_titles(rows,'langfuse'),path,True,parent='ClickHouse',parent_board_count=len(rows),parent_posting_ids=[r['posting_id'] for r in rows],title_filter='whole word Langfuse')
    # Langfuse dedicated Ashby board: complete offline board populations from archive.
    # Live jobs.ashbyhq.com/langfuse is currently 404; the latest in-window complete archive
    # is retained as the latest available complete board observation.
    langfuse_board_caps=sorted(
        [c for c in langfuse_ashby_archives if c.get('source_id')=='langfuse-ashby' and not c.get('error')],
        key=lambda c:c['timestamp'],
    )
    if len(langfuse_board_caps)<2:raise ValueError('Langfuse complete Ashby board history requires at least two verified captures')
    latest_langfuse=langfuse_board_caps[-1]
    for source in langfuse_board_caps:
        html,path=verified(source,langfuse_ashby_discovery)
        rows=parse_board(html,'Langfuse')
        if source is latest_langfuse:
            snapshot(
                'langfuse','complete_official_ats_board',source,rows,path,False,
                live_endpoint_status=404,live_endpoint_url='https://jobs.ashbyhq.com/langfuse',
                observation_basis='latest_in_window_complete_archive_board_while_live_endpoint_unavailable',
            )
        else:
            snapshot('langfuse','complete_official_ats_board',source,rows,path,True)
    # Continue dedicated Ashby board: two in-window complete archives (live board currently 404).
    continue_board_caps=sorted(
        [c for c in continue_ashby_archives if c.get('source_id')=='continue-ashby' and not c.get('error')],
        key=lambda c:c['timestamp'],
    )
    if len(continue_board_caps)<2:raise ValueError('Continue complete Ashby board history requires at least two verified captures')
    latest_continue=continue_board_caps[-1]
    for source in continue_board_caps:
        html,path=verified(source,continue_ashby_discovery)
        rows=parse_board(html,'Continue')
        if source is latest_continue:
            snapshot(
                'continue','complete_official_ats_board',source,rows,path,False,
                live_endpoint_status=404,live_endpoint_url='https://jobs.ashbyhq.com/continue',
                observation_basis='latest_in_window_complete_archive_board_while_live_endpoint_unavailable',
            )
        else:
            snapshot('continue','complete_official_ats_board',source,rows,path,True)
    current=next(x for x in parent_apis if x['source_id']=='coreweave-parent-api');text,path=s.source(current);rows=greenhouse(json.loads(text))
    snapshot('wandb','explicit_brand_titles_in_parent_ats',current,branded_titles(rows,'wandb'),path,parent='CoreWeave',parent_board_count=len(rows),parent_posting_ids=[r['posting_id'] for r in rows],title_filter='Weights & Biases or Weights and Biases')
    for source in wandb_archives:
        text,path=verified(source,last_search);rows=greenhouse(json.loads(text))
        snapshot('wandb','explicit_brand_titles_in_parent_ats',source,branded_titles(rows,'wandb'),path,True,parent='CoreWeave',parent_board_count=len(rows),parent_posting_ids=[r['posting_id'] for r in rows],title_filter='Weights & Biases or Weights and Biases')
    # CrewAI: current full widget feed and dated adverts; no invented board baseline.
    current=next(x for x in discovery if x['source_id']=='crewai-widget');text,path=s.source(current);payload=json.loads(text)
    if payload.get('name')!='CrewAI' or not isinstance(payload.get('jobs'),list):raise ValueError('Wrong Workable employer/feed')
    crew_rows=unique_rows([{'posting_id':j['shortcode'],'title':j['title']} for j in payload['jobs']])
    llms,_=s.source(next(x for x in discovery if x['source_id']=='crewai-llms'));declared=re.search(r'(\d+) current openings',llms)
    if not declared or int(declared.group(1))!=len(crew_rows):raise ValueError('Official Workable feed and declared count differ; review source times')
    crew_current={'snapshot_at':current['observed_at'],'source_file':path,'source_url':current['response_url'],'listed_count':len(crew_rows),'listings':crew_rows}
    adverts=[]
    for source in extra:
        if source['source_id']!='crewai-individual-role' or source.get('error'):continue
        html,path=verified(source,original_search);p=Meta();p.feed(html);title=p.values.get('og:title','');description=p.values.get('og:description','')
        if not title.endswith(' - CrewAI') or not description:raise ValueError('Archived role lacks specific CrewAI advertisement metadata')
        code=urlsplit(source['original_url']).path.rstrip('/').rsplit('/',1)[-1]
        adverts.append({'posting_id':code,'title':title.removesuffix(' - CrewAI'),'description_excerpt':description,'snapshot_at':source['snapshot_at'],
                        'source_file':path,'source_url':source['response_url'],'present_in_current_board':code in {r['posting_id'] for r in crew_rows},
                        'active_at_archive_capture':None,'complete_historical_board':False})
    comparisons=[]
    for cid,items in pools.items():
        # Compare archived snapshots only against the latest observation of the same population.
        by_population={}
        for item in items:
            by_population.setdefault(item['population'], []).append(item)
        for population, group in by_population.items():
            latest=next(x for x in group if not x['archived'])
            for old in group:
                if old['archived']:
                    comparisons.append(compare(old, latest))
    complete_populations={'complete_official_career_list','complete_official_ats_board'}
    full=old_companies|{c['company_id'] for c in comparisons if c['population'] in complete_populations}
    scoped={c['company_id'] for c in comparisons if c['population'] not in complete_populations}-full
    all_companies=old_companies|{'chroma','continue','crewai','langfuse','replicate','wandb'}
    return {'status':'collection_review_complete_with_explicit_population_limits',
        'summary':{'complete_official_population_history_companies':sorted(full),'complete_official_population_history_count':len(full),
                   'additional_scoped_history_companies':sorted(scoped),'companies_with_any_paired_public_channel':len(full|scoped),
                   'company_without_paired_historical_population':sorted(all_companies-(full|scoped)),
                   'companies_without_complete_official_population_history':sorted(all_companies-full),
                   'new_attributable_current_ats_board':'CrewAI Workable','new_complete_native_career_history':'Chroma',
                   'new_complete_official_ats_board_history':'Langfuse Ashby; Continue Ashby'},
        'population_definitions':{'complete_official_career_list':'All publicly listed specific roles on the company-endorsed native list; not payroll or completed hires.',
             'complete_official_ats_board':'All publicly listed posting IDs on the company-named Ashby/Greenhouse board landing payload decoded offline from window.__appData or equivalent complete board HTML/JSON.',
             'yc_employer_directory_channel':'Employer job listings published on the identity-matched YC channel only. Empty arrays are observed zero for this channel, not absence of company hiring.',
             'explicit_brand_titles_in_parent_ats':'Only roles explicitly naming the cohort brand in the title. Parent totals and unbranded roles are not attributed to the cohort company.'},
        'snapshots':pools,'comparisons':comparisons,'crewai_current_board':crew_current,'crewai_historical_advertisements':adverts,
        'source_gaps':{'crewai':'Two historical advertisement pages and four current roles are retained; no complete historical board population establishes stock change or hires.',
                       'continue':'Complete Ashby board history is retained from two in-window archived board landings (including one query-string capture of the same board). Live jobs.ashbyhq.com/continue currently returns 404, so the latest in-window complete archive is the latest available complete board observation. YC directory channel remains separate and scoped.',
                       'langfuse':'Complete Ashby board history is retained from archived board landings. Live jobs.ashbyhq.com/langfuse currently returns 404, so the latest in-window complete archive is the latest available complete board observation. Parent ClickHouse brand-title comparisons remain separate and scoped.',
                       'wandb':'Dedicated weights_and_biases endpoint is unavailable. Paired counts use only explicit brand titles in the CoreWeave account.',
                       'replicate':'Paired YC-only zero-listing observations are retained; parent Cloudflare jobs are not substituted as Replicate hiring.'},
        'limits':['The original 18-company cohort is preserved, including companies whose directory status changes.',
                  'No missing weeks are filled with zero and no regular weekly hiring trajectory is inferred.',
                  'Prefix archive lookups are limited to 250 results with monthly collapsing; unavailable or unreturned captures do not establish global source absence.',
                  'Posting additions/removals are listing observations, not completed hires or headcount changes.',
                  'Brand-title changes can move existing parent posting IDs into a subset; newly selected IDs are split by prior presence in the full parent population.',
                  'Historical payloads are decoded offline. The Chroma browser fallback captures the archived network body with scripts disabled and validates its Memento clock.',
                  'When a live complete board endpoint is unavailable, a later in-window complete archive board may be used as the latest available complete observation; this is not a restored live feed.',
                  'Selected-channel and parent-title comparisons do not satisfy whole-company temporal ground truth.',
                  'Frozen benchmark corpora, relevance judgments, rater decisions and pilot results are unchanged.'],
        'input_sha256':{**s.inputs,'evaluation/remaining_history_review.py':sha(root/'evaluation/remaining_history_review.py'),'collectors/archive_browser.py':sha(root/'collectors/archive_browser.py'),'evaluation/ats_history.py':sha(root/'evaluation/ats_history.py')}}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args();r=build();out=DIRECTORY/'review.json'
    if a.check:
        if json.loads(out.read_text())!=r:raise SystemExit('Remaining-company review differs from frozen inputs.')
    else:out.write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'summary':r['summary'],'comparisons':[{k:v for k,v in c.items() if k not in ['newly_observed','no_longer_observed','retained']} for c in r['comparisons']]},indent=2))


if __name__=='__main__':main()
