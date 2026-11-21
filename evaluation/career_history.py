"""Replay dated, server-rendered official career lists without executing archive JS."""
import argparse
from collections import defaultdict
from datetime import timezone
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT/'evaluation/cohort-history-followup'


class LlamaRoles(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.in_list=0; self.saw_list=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='ul':
            if self.in_list:
                self.in_list+=1
            elif 'RoleList' in a.get('class','').split():
                self.in_list=1;self.saw_list=True
        if tag=='a' and self.in_list and a.get('href','').startswith('/careers/') and a.get('aria-label'):
            self.rows.append({'posting_id':a['href'],'title':a['aria-label'],'url':'https://www.llamaindex.ai'+a['href'],
                'listing_type':'talent_pool' if 'don\u2019t see your role' in a['aria-label'].lower() else 'specific_role'})
    def handle_endtag(self,tag):
        if tag=='ul' and self.in_list:
            self.in_list-=1


def parse_roles(company,html):
    if company=='llamaindex':
        p=LlamaRoles();p.feed(html)
        if not p.saw_list or not p.rows:
            raise ValueError('No complete server-rendered RoleList; coverage unknown, not zero.')
        rows=p.rows
    else:
        raise ValueError('No reviewed historical listing parser for '+company)
    ids=[r['posting_id'] for r in rows]
    if len(ids)!=len(set(ids)):
        raise ValueError('Duplicate career posting identity')
    return rows


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build(directory=DIRECTORY):
    discovery=json.loads((directory/'discovery.json').read_text())
    searches=json.loads((directory/'archive-search.json').read_text())
    captures=json.loads((directory/'archive-captures.json').read_text())
    inputs={n:sha(directory/n) for n in ['discovery.json','archive-search.json','archive-captures.json']}
    baseline_path=directory.parent/'cohort-job-history/manifest.json'
    baseline=json.loads(baseline_path.read_text())
    prior_history={c['company_id'] for c in baseline['companies'] if c['historical_in_window']}
    inputs['../cohort-job-history/manifest.json']=sha(baseline_path)
    snapshots=[]; unavailable=[]
    for source in discovery+captures:
        if source.get('file'):
            if sha(directory/source['file'])!=source['sha256']:
                raise ValueError('Career source checksum mismatch')
            inputs[source['file']]=source['sha256']
        cid=source['company_id']
        if cid!='llamaindex':
            continue
        if source.get('http_status',source.get('status'))!=200:
            unavailable.append({'company_id':cid,'reason':'source_retrieval_failed'});continue
        archived='timestamp' in source
        if archived:
            if not source.get('capture_verified'):
                raise ValueError('Unverified archive capture')
            when=parsedate_to_datetime(source['memento_datetime']).astimezone(timezone.utc)
            if when.strftime('%Y%m%d%H%M%S')!=source['timestamp'] or when.isoformat().replace('+00:00','Z')!=source['snapshot_at']:
                raise ValueError('Archive capture clock mismatch')
            search=next(x for x in searches if x['company_id']==cid)
            if not any(x['timestamp']==source['timestamp'] and x['original']==source['original_url'] for x in search['captures']):
                raise ValueError('Archive not present in retained CDX discovery')
            snapshot_at=source['snapshot_at'];url=source['original_url']
        else:
            snapshot_at=source['observed_at'];url=source['response_url']
        u=urlsplit(url)
        if u.hostname not in {'www.llamaindex.ai','llamaindex.ai'} or u.path.rstrip('/')!='/careers' or u.query:
            raise ValueError('Not the complete official career landing page')
        rows=parse_roles(cid,(directory/source['file']).read_text())
        snapshots.append(dict(company_id=cid,snapshot_at=snapshot_at,observed_at=source['observed_at'],
            source_file=source['file'],source_sha256=source['sha256'],archived=archived,
            capture_url=source.get('response_url'),specific_roles=sum(r['listing_type']=='specific_role' for r in rows),
            talent_pool_entries=sum(r['listing_type']=='talent_pool' for r in rows),listings=rows))
    for source in searches:
        if source.get('file'):
            if sha(directory/source['file'])!=source['sha256']:
                raise ValueError('CDX source checksum mismatch')
            inputs[source['file']]=source['sha256']
    groups=defaultdict(list)
    for s in snapshots: groups[s['company_id']].append(s)
    comparisons=[]
    for cid,rows in groups.items():
        rows.sort(key=lambda s:s['snapshot_at']); latest=rows[-1]
        for prior in rows[:-1]:
            before={x['posting_id'] for x in prior['listings'] if x['listing_type']=='specific_role'}
            after={x['posting_id'] for x in latest['listings'] if x['listing_type']=='specific_role'}
            comparisons.append(dict(company_id=cid,baseline_at=prior['snapshot_at'],latest_at=latest['snapshot_at'],
                baseline_specific_roles=len(before),latest_specific_roles=len(after),net_posting_change=len(after)-len(before),
                newly_observed=sorted(after-before),no_longer_observed=sorted(before-after),retained=sorted(before&after)))
    current_render_crosscheck=None
    browser=directory.parent/'browser-observations/llamaindex-2026-11-21'
    if (browser/'manifest.json').exists():
        bm=json.loads((browser/'manifest.json').read_text())
        if sha(browser/'rendered.html')!=bm['sha256']:
            raise ValueError('Browser observation checksum mismatch')
        rendered=parse_roles('llamaindex',(browser/'rendered.html').read_text())
        latest=max(groups['llamaindex'],key=lambda s:s['snapshot_at'])
        if rendered!=latest['listings']:
            raise ValueError('Current rendered list differs from current raw source; preserve separate snapshots and review.')
        current_render_crosscheck={'status':'same_listing_entries','entries':len(rendered),'observed_at':bm['observed_at'],'manifest':'evaluation/browser-observations/llamaindex-2026-11-21/manifest.json'}
        inputs['../browser-observations/llamaindex-2026-11-21/manifest.json']=sha(browser/'manifest.json')
        inputs['../browser-observations/llamaindex-2026-11-21/rendered.html']=sha(browser/'rendered.html')
    newly_historical={c['company_id'] for c in comparisons}-prior_history
    return dict(current_browser_crosscheck=current_render_crosscheck,method='Offline exact official RoleList parsing; historical HTML is never rehydrated with live JavaScript.',
        independent_annotation=False,input_sha256=inputs,snapshots=snapshots,comparisons=comparisons,
        summary=dict(new_historical_companies=len(newly_historical),
            historical_companies_including_previous_two=len(prior_history|newly_historical),
            remaining_companies_without_comparable_history=len(baseline['companies'])-len(prior_history|newly_historical)),
        limits=['Published career lists may differ from ATS boards; do not mix their counts within a comparison.',
               'Talent-pool entries are retained separately and excluded from specific-role stock.',
               'Newly observed and no-longer-observed postings are not hires.',
               'Unretrievable captures and JS-only shells remain unknown; no zero stock inferred.',
               'A new Selenium rendering of an archive may fetch live APIs; it is not admissible historical stock.'],
        retrieval_failures=[{'company_id':c['company_id'],'timestamp':c['timestamp'],'error':c['error']} for c in captures if c.get('error')])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args();r=build();out=DIRECTORY/'review.json'
    if a.check:
        if json.loads(out.read_text())!=r:raise SystemExit('Career review changed; rebuild.')
    else:out.write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'summary':r['summary'],'comparisons':r['comparisons']},indent=2))


if __name__=='__main__':main()
