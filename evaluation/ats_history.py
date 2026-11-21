"""Offline, source-verified Ashby board history from embedded archived JSON."""
import argparse
from datetime import timezone
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
DIRECTORY=ROOT/'evaluation/cohort-ats-history'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_board(html,company_name):
    markers=list(re.finditer(r'window\.__appData\s*=\s*',html))
    if len(markers)!=1: raise ValueError('Exactly one embedded Ashby board payload required; no live script execution.')
    data,_=json.JSONDecoder().raw_decode(html[markers[0].end():])
    if data.get('posting') is not None or data.get('maintenanceMode'):
        raise ValueError('Not an available complete board landing page')
    if data.get('organization',{}).get('name','').casefold()!=company_name.casefold():
        raise ValueError('Board company mismatch')
    board=data.get('jobBoard')
    if not isinstance(board,dict) or not isinstance(board.get('jobPostings'),list) or board.get('stealthAccess') or board.get('hasNextPage'):
        raise ValueError('No complete public board payload')
    return listing_rows(board['jobPostings'])


class GreenhouseRows(HTMLParser):
    def __init__(self,slug):
        super().__init__();self.slug=slug;self.rows=[];self.in_row=False;self.in_title=False;self.current=None;self.title=[];self.first_p=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='tr' and 'job-post' in a.get('class','').split():self.in_row=True;self.current=None;self.title=[];self.first_p=False
        if self.in_row and tag=='a':
            u=urlsplit(a.get('href',''));m=re.fullmatch('/'+re.escape(self.slug)+r'/jobs/(\d+)',u.path)
            if u.hostname=='job-boards.greenhouse.io' and m:self.current=m.group(1)
        if self.in_row and tag=='p' and not self.first_p:self.in_title=True;self.first_p=True
    def handle_data(self,text):
        if self.in_title:self.title.append(text)
    def handle_endtag(self,tag):
        if tag=='p':self.in_title=False
        if tag=='tr' and self.in_row:
            if not self.current or not ''.join(self.title).strip():raise ValueError('Incomplete Greenhouse posting row')
            self.rows.append({'id':self.current,'title':''.join(self.title).strip()});self.in_row=False


def parse_greenhouse(html,slug):
    if 'class="job-posts"' not in html:raise ValueError('No complete Greenhouse landing list')
    p=GreenhouseRows(slug);p.feed(html)
    count=re.search(r'data-testid="job-count-header"[^>]*>(\d+) jobs?',html)
    if count and int(count.group(1))!=len(p.rows):raise ValueError('Greenhouse count header disagrees with listing rows')
    if not p.rows:raise ValueError('Greenhouse empty list not established as observed zero')
    return listing_rows(p.rows)


def listing_rows(jobs):
    rows=[];seen=set()
    for job in jobs:
        if job.get('isListed') is False:continue
        jid=job.get('id');title=job.get('title')
        if type(jid) in {str,int}:jid=str(jid)
        if not isinstance(jid,str) or not jid or jid in seen or not isinstance(title,str) or not title.strip():
            raise ValueError('Missing or duplicate posting identity/title')
        seen.add(jid);rows.append({'posting_id':jid,'title':title})
    return sorted(rows,key=lambda r:r['posting_id'])


class Frames(HTMLParser):
    def __init__(self):super().__init__();self.urls=[]
    def handle_starttag(self,tag,attrs):
        if tag=='iframe':self.urls.append(dict(attrs).get('src',''))


def build(directory=DIRECTORY):
    root=directory.parents[1];inputs={}
    def load(path):
        inputs[str(path.relative_to(root))]=sha(path)
        return json.loads(path.read_text())
    discovery=load(directory/'discovery.json');captures=load(directory/'captures.json')
    extra=load(directory/'weaviate-discovery.json');captures+=load(directory/'weaviate-captures.json')
    alternate_search=load(directory/'remaining-board-search.json');captures+=load(directory/'alternate-captures.json')
    arize_search=load(directory/'arize-discovery.json');captures+=load(directory/'arize-captures.json')
    baseline=load(root/'evaluation/cohort-job-history/manifest.json')
    prior_career=load(root/'evaluation/cohort-history-followup/review.json')
    company_map={c['company_id']:c for c in load(root/'data/registry/cohort.json')['companies']}
    board_audit=load(root/'evaluation/cohort-source-audit/board-audit.json')
    # The new board link is observed inside an official-company page's iframe.
    browser=root/'evaluation/browser-observations/weaviate-2026-11-21'
    bm=load(browser/'manifest.json');dom=browser/'rendered.html';inputs[str(dom.relative_to(root))]=sha(dom)
    if sha(dom)!=bm['sha256'] or bm['company_id']!='weaviate' or urlsplit(bm['response_url']).hostname!='weaviate.io':
        raise ValueError('Weaviate official browser source mismatch')
    frames=Frames();frames.feed(dom.read_text())
    if not any(urlsplit(u).hostname=='jobs.ashbyhq.com' and urlsplit(u).path.rstrip('/')=='/weaviate' for u in frames.urls):
        raise ValueError('Weaviate official iframe mapping missing')
    arize_check=load(directory/'arize-candidate-check.json')
    arize_page=root/'evaluation/cohort-history-followup/sources/arize-careers.html'
    inputs[str(arize_page.relative_to(root))]=sha(arize_page)
    match=re.search(r'jobs:\s*',arize_page.read_text())
    official,_=json.JSONDecoder().raw_decode(arize_page.read_text()[match.end():])
    arize_api=load(directory/arize_check['file'])
    if sha(directory/arize_check['file'])!=arize_check['sha256'] or {str(j['id']) for j in official}!={str(j['id']) for j in arize_api['jobs']}:
        raise ValueError('Arize API does not match official career-page job identities')
    sources=discovery+extra+alternate_search+arize_search
    for source in sources:
        if source.get('file'):
            p=directory/source['file'];inputs[str(p.relative_to(root))]=sha(p)
            if sha(p)!=source['sha256']:raise ValueError('ATS discovery checksum mismatch')
    snapshots=[]
    for source in captures:
        if source.get('error'):continue
        cid=source['company_id'];name=company_map[cid]['name'];ts=source['timestamp'];u=urlsplit(source['original_url'])
        slug={'deepset':'deepsetai','browserbase':'browserbaseinc','sourcegraph':'sourcegraph91','arize':'arizeai'}.get(cid,cid)
        greenhouse=cid in {'browserbase','sourcegraph','arize'}
        expected_host='job-boards.greenhouse.io' if greenhouse else 'jobs.ashbyhq.com'
        if u.hostname!=expected_host or u.path.rstrip('/')!='/'+slug or u.query:
            raise ValueError('Not an unfiltered board landing URL')
        search=next((s for s in sources if s['company_id']==cid and any(c['timestamp']==ts and c['original']==source['original_url'] for c in s.get('captures',[]))),None)
        if search is None:
            raise ValueError('Capture missing from retained CDX')
        when=parsedate_to_datetime(source['memento_datetime']).astimezone(timezone.utc)
        if not source.get('capture_verified') or when.strftime('%Y%m%d%H%M%S')!=ts or when.isoformat().replace('+00:00','Z')!=source['snapshot_at']:
            raise ValueError('ATS archive clock mismatch')
        if not '20251101000000'<=ts<='20261121235959':raise ValueError('Outside study window')
        path=directory/source['file'];inputs[str(path.relative_to(root))]=sha(path)
        if sha(path)!=source['sha256']:raise ValueError('ATS archived HTML checksum mismatch')
        rows=parse_greenhouse(path.read_text(),slug) if greenhouse else parse_board(path.read_text(),name)
        snapshots.append(dict(company_id=cid,source_url=source['response_url'],source_file=str(path.relative_to(root)),
            source_sha256=sha(path),snapshot_at=source['snapshot_at'],observed_at=source['observed_at'],
            population='Public listed posting IDs on the attributable complete board, including all displayed categories.',archived=True,listings=rows))
    # Compare to the already frozen complete API populations, not web search counts.
    for cid in sorted({s['company_id'] for s in snapshots}):
        if cid=='arize':
            path=directory/arize_check['file'];now=arize_check['observed_at'];url=arize_check['url']
        elif cid=='weaviate':
            source=next(s for s in extra if 'job_count' in s)
            path=directory/source['file'];now=source['observed_at'];url=source['response_url']
        else:
            mapped=next(c for c in board_audit['companies'] if c['company_id']==cid)['boards']
            if not any(b['slug']=={'deepset':'deepsetai','browserbase':'browserbaseinc','sourcegraph':'sourcegraph91','arize':'arizeai'}.get(cid,cid) for b in mapped):raise ValueError('Official mapping absent')
            board=next(c for c in baseline['companies'] if c['company_id']==cid)['boards'][0]
            latest=max(board['observations'],key=lambda o:o['snapshot_at']);path=root/'evaluation/cohort-job-history'/latest['file'];now=latest['snapshot_at'];url=latest['source_url']
            original=next(s for s in baseline['sources'] if s['file']==latest['file'])
            if sha(path)!=original['sha256']:raise ValueError('Baseline current API checksum mismatch')
        payload=load(path)
        if not isinstance(payload.get('jobs'),list):raise ValueError('Missing current complete API job list')
        rows=listing_rows(payload['jobs'])
        snapshots.append(dict(company_id=cid,source_url=url,source_file=str(path.relative_to(root)),source_sha256=sha(path),
            snapshot_at=now,observed_at=now,population='Public listed posting IDs on the attributable complete board, including all displayed categories.',archived=False,listings=rows))
    comparisons=[]
    for prior in snapshots:
        if not prior['archived']:continue
        latest=next(s for s in snapshots if s['company_id']==prior['company_id'] and not s['archived'])
        left={r['posting_id'] for r in prior['listings']};right={r['posting_id'] for r in latest['listings']}
        comparisons.append(dict(company_id=prior['company_id'],baseline_at=prior['snapshot_at'],latest_at=latest['snapshot_at'],baseline_listed=len(left),latest_listed=len(right),
            net_posting_change=len(right)-len(left),newly_observed=sorted(right-left),no_longer_observed=sorted(left-right),retained=sorted(left&right)))
    old={c['company_id'] for c in baseline['companies'] if c['historical_in_window']}
    old|={c['company_id'] for c in prior_career['comparisons']}
    new={c['company_id'] for c in comparisons}-old;all_history=old|new
    return dict(method='Offline archived Ashby window.__appData JSON and server-rendered Greenhouse rows; no JavaScript execution or live API hydration.',
        input_sha256=inputs,snapshots=snapshots,comparisons=comparisons,
        summary=dict(additional_historical_companies=sorted(new),historical_companies=sorted(all_history),historical_company_count=len(all_history),
            remaining_companies_without_comparable_history=sorted(set(company_map)-all_history),
            current_verified_ats_boards=sum(c['current_listed'] is not None for c in baseline['companies'])+2),
        limits=['Posting stocks and observed identity changes are not hires, payroll headcount or skill-specific hiring growth.',
            'E2B baseline is only four days before the current snapshot; other comparisons have irregular intervals.',
            'Archive HTML and corresponding API populations use posting IDs; no individual role page or filtered search is a complete board.',
            'Current Weaviate mapping is iframe verified; Arize mapping matches all official career-page posting IDs. Earlier benchmark corpora, qrels and participant records are unchanged.'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args();r=build();out=DIRECTORY/'review.json'
    if a.check:
        if json.loads(out.read_text())!=r:raise SystemExit('ATS review differs; rebuild and review.')
    else:out.write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'summary':r['summary'],'comparisons':[{k:v for k,v in c.items() if k not in ['newly_observed','no_longer_observed','retained']} for c in r['comparisons']]},indent=2))


if __name__=='__main__':main()
