"""Freeze a mixed-source follow-up round without changing earlier experiments."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import requests
from collectors.api_http import HttpClient
from collectors.common import job_fields, plain_text
from collectors.records import make_record, utc_now, validate_records
from collectors.sources import GitHubCollector, snapshot_header

REPOS = {'langchain': 'langchain-ai/langchain', 'crewai': 'crewAIInc/crewAI',
         'langfuse': 'langfuse/langfuse'}
FUNDING = [
    ('langchain', 'https://www.langchain.com/blog/series-c'),
    ('llamaindex', 'https://www.llamaindex.ai/blog/announcing-our-series-a-and-llamacloud-general-availability'),
    ('browserbase', 'https://www.browserbase.com/blog/series-b-and-beyond'),
]


def iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def weekly_snapshots(snapshot, weeks=8):
    """Partition real commits into complete ISO weeks; never backdate observation."""
    observed = datetime.fromisoformat(snapshot['observed_at'].replace('Z', '+00:00'))
    end = (observed - timedelta(days=observed.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    for index in range(weeks):
        start = end - timedelta(days=7)
        selected = [c for c in snapshot['payload']['commits']
                    if start <= datetime.fromisoformat(c['committed_at'].replace('Z', '+00:00')) < end]
        part = copy.deepcopy(snapshot)
        part['payload']['commits'] = selected
        part['coverage'].update(window_start=iso(start - timedelta(seconds=1)),
                                window_end=iso(end - timedelta(seconds=1)), window_days=7)
        record = GitHubCollector().normalize(part)[0]
        metadata = record['metadata']
        metadata['activity_window']['commits'] = selected
        # Counters were observed today, not in these historical weeks.
        for key in ['stargazers_count', 'forks_count', 'open_issues_count']:
            metadata[key] = None
        # Rebuild identity after changing metadata and provide an explicit source passage.
        yield make_record(source_type='github', source_url=record['source_url'],
            title=f"{snapshot['target']} commits {start.date()} to {(end-timedelta(days=1)).date()}",
            text=f"{snapshot['target']} recorded {len(selected)} default-branch commits during "
                 f"{start.date()} to {(end-timedelta(days=1)).date()}. "
                 'Counts are reconstructed from dated commits; repository counters are unavailable for this historical week.',
            publisher=snapshot['company_name'], startup_name=snapshot['company_name'],
            company_id=snapshot['company_id'], observed_at=snapshot['observed_at'],
            event_at=iso(end-timedelta(seconds=1)), event_type='repository_activity_window',
            collector_version='mixed-corpus/1.0', metadata=metadata)
        end = start


def collect(out):
    if out.exists():
        raise ValueError(f'refusing to overwrite round: {out}')
    observed = utc_now()
    cohort = json.loads((ROOT/'data/registry/cohort.json').read_text())
    companies = {c['company_id']: c for c in cohort['companies']}
    sources, raw, records = [], {}, []

    def retain(name, url, body):
        raw[name] = body
        sources.append({'file': 'sources/'+name, 'api_url': url, 'observed_at': observed,
                        'sha256': hashlib.sha256(body).hexdigest()})

    def fetch(url):
        response = requests.get(url, timeout=40, headers={'User-Agent':'TrendScout-research/1.0'})
        response.raise_for_status()
        return response

    for company, url in FUNDING:
        response = fetch(url)
        html = response.text
        retain(company+'-funding.html', response.url, response.content)
        title = re.search(r'<title[^>]*>(.*?)</title>', html, re.S|re.I)
        article = re.search(r'<article\b[^>]*>(.*?)</article>', html, re.S|re.I)
        passage = plain_text(article.group(1) if article else html)
        if not re.search(r'\b(raised|funding|financing)\b', passage, re.I):
            raise ValueError(f'funding passage absent: {url}')
        # Only structured publication timestamps, never a guessed event date.
        date = re.search(r'"datePublished"\s*:\s*"([^"<>]+)"', html)
        records.append(make_record(source_type='funding', source_url=response.url,
            title=plain_text(title.group(1)) if title else company+' funding', text=passage,
            publisher=companies[company]['name'], startup_name=companies[company]['name'],
            company_id=company, observed_at=observed, published_at=date.group(1) if date else None,
            event_type='funding_announcement', collector_version='mixed-corpus/1.0',
            metadata={'synthetic':False, 'event_date_basis':'Unknown unless stated and reviewed in passage'}))
        print(company, 'funding collected', flush=True)

    jobs = []
    for company in ['langchain', 'llamaindex']:
        url = 'https://api.ashbyhq.com/posting-api/job-board/'+company
        response = fetch(url)
        retain(company+'-jobs.json', url, response.content)
        for job in response.json()['jobs']:
            if not job.get('isListed', True):
                continue
            text = job.get('descriptionPlain') or plain_text(job.get('descriptionHtml'))
            metadata = job_fields(job['title'], text)
            metadata.update(source_record_id='ashby:'+str(job.get('id',job['jobUrl'])),
                source_control_group='company:'+company, synthetic=False,
                publication_caveat='Current publication timestamp is not proof of first hiring or historical availability.')
            metadata['skills'] += [s for s in ['retrieval','evaluation','mlops','rag','nlp']
                                  if re.search(r'\b'+s+r'\b', text, re.I)]
            jobs.append(make_record(source_type='job', source_url=job['jobUrl'], title=job['title'],
                text=text, publisher=companies[company]['name'], startup_name=companies[company]['name'],
                company_id=company, observed_at=observed, published_at=job.get('publishedAt'),
                event_type='job_snapshot', collector_version='mixed-corpus/1.0', metadata=metadata))
    # Freeze selection before running any retriever: all LlamaIndex jobs, then
    # LangChain jobs ranked by explicit target-skill count, breaking ties by URL.
    jobs.sort(key=lambda r:(r['company_id']!='llamaindex',
                           -len(set(r['metadata']['skills']) & {'retrieval','evaluation','mlops','rag','nlp'}), r['source_url']))
    if len(jobs)<18:
        raise ValueError('fewer than 18 listed jobs')
    records.extend(jobs[:18])
    print('18 jobs selected', flush=True)
    client = HttpClient(attempts=2, max_wait=10)
    for company, repo in REPOS.items():
        snapshot = GitHubCollector(window_days=63).collect(client,
            snapshot_header('github', repo, company, companies[company]['name'], observed))
        body = (json.dumps(snapshot, ensure_ascii=False)+'\n').encode()
        retain(company+'-commits.json', 'https://api.github.com/repos/'+repo+'/commits', body)
        records.extend(weekly_snapshots(snapshot))
        print(company, len(snapshot['payload']['commits']), 'commits; 8 weeks', flush=True)
    for record in records:
        record['metadata']['synthetic'] = False
    if validate_records(records) or len(records)!=45:
        raise ValueError('invalid mixed corpus')
    out.mkdir(parents=True)
    (out/'sources').mkdir()
    for name, body in raw.items():
        (out/'sources'/name).write_bytes(body)
    content = ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records).encode()
    (out/'records.jsonl').write_bytes(content)
    manifest = {'status':'frozen_mixed_sources', 'synthetic_fixture':False,
        'document_count':len(records), 'observed_at':observed, 'sources':sources,
        'snapshot_sha256':hashlib.sha256(content).hexdigest(),
        'selection':'3 primary funding documents, 18 skill-prioritized listed jobs, 8 complete ISO weeks for 3 repositories',
        'study_revision':'Mixed-source follow-up; original 18-company cohort and 28 question texts preserved. Observation window extends beyond original 2026-10-30 freeze.',
        'limitations':['Historical GitHub activity is reconstructed from default-branch commits available at observation time.',
            'Current job-board publications do not establish hiring growth; closed historical jobs are unavailable.',
            'Funding announcement publication is not automatically the funding event date.',
            'No public-voice coverage; no causal funding-to-hiring claim.',
            '45 source records include 24 weekly observations, not 45 independent documentary origins.']}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'records':45,'out':str(out)},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'evaluation/mixed')
    collect(parser.parse_args().out)
