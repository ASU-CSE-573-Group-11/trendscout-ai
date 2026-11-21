"""Integrate newly discovered archive query variants without changing old freezes."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import requests

from collectors.records import utc_now
from evaluation.cohort_jobs import normalize, comparison, replay as replay_jobs
from evaluation.real_round import ROOT
from signals.pipeline import run_trend_pipeline, write_trend_bundle
from signals.contract import to_payload


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def collect(out):
    if (out/'job-records.jsonl').exists():
        raise ValueError('Refusing to overwrite archive follow-up observations')
    m=json.loads((out/'manifest.json').read_text())
    base=ROOT/'evaluation/cohort-job-history'
    replay_jobs(base)
    baseline=json.loads((base/'manifest.json').read_text())
    companies={c['company_id']:c for c in json.loads((base/'cohort.json').read_text())['companies']}
    frozen_capture_times={c['company_id']:{o['snapshot_at'] for b in c['boards'] for o in b['observations']} for c in baseline['companies']}
    observations=[];new=[]
    for source in m['boards']:
        if not source.get('file'):
            continue
        if sha(out/source['file'])!=source['sha256']:
            raise ValueError('Archive lookup source checksum mismatch')
        for capture in source.get('captures',[]):
            original=capture['original'];parsed=urlsplit(original);canonical=urlsplit(source['api_url'])
            # The compensation option changes fields, not the listing filter.
            # Unknown query options may select a different population.
            if parsed.hostname!=canonical.hostname or parsed.path!=canonical.path or any(k!='includeCompensation' or v!=['true'] for k,v in parse_qs(parsed.query).items()):
                continue
            timestamp=capture['timestamp']
            clock=f'{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}T{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}Z'
            if clock in frozen_capture_times.get(source['company_id'],set()):
                continue
            if not '2025-11-01T00:00:00Z'<=clock<'2026-11-22T00:00:00Z':
                continue
            url=f'https://web.archive.org/web/{timestamp}id_/{original}'
            response=requests.get(url,timeout=40,headers={'User-Agent':'TrendScout-research/1.0'})
            response.raise_for_status()
            when=parsedate_to_datetime(response.headers['Memento-Datetime']).astimezone(timezone.utc)
            if when.strftime('%Y%m%d%H%M%S')!=timestamp:
                raise ValueError('Archive timestamp mismatch')
            filename=f"sources/{source['company_id']}-{timestamp}.json"
            (out/filename).write_bytes(response.content)
            archive={'verified':True,'captured_at':clock,'url':response.url,
                     'payload_sha256':sha(out/filename),'verification':'Prefix CDX capture equals Memento-Datetime; payload retained.'}
            observed=utc_now()
            board=next(b for c in baseline['companies'] if c['company_id']==source['company_id'] for b in c['boards'] if b['api_url']==source['api_url'])
            batch=normalize(response.json(),companies[source['company_id']],board,response.url,observed,clock,archive)
            new.extend(batch)
            observations.append({'company_id':source['company_id'],'board_type':board['type'],
                'file':filename,'sha256':sha(out/filename),'source_url':response.url,'original_url':original,
                'snapshot_at':clock,'observed_at':observed,'archive_capture':archive,
                'memento_datetime':response.headers['Memento-Datetime'],'count':len(batch)})
    (out/'job-records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in new))
    merged=records(base/'records.jsonl')+new
    write_trend_bundle(run_trend_pipeline(merged),out/'signals')
    m.update(archive_observations=observations,additional_job_observations=len(new),
        baseline_directory='evaluation/cohort-job-history',baseline_manifest_sha256=sha(base/'manifest.json'),
        baseline_records_sha256=sha(base/'records.jsonl'),
        output_sha256={str(p.relative_to(out)):sha(p) for p in [out/'job-records.jsonl',*sorted((out/'signals').iterdir())]})
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    return replay(out)


def replay(out):
    m=json.loads((out/'manifest.json').read_text())
    for source in [*m['boards'],*m['additional_mapping_sources']]:
        if source.get('file') and sha(out/source['file'])!=source['sha256']:
            raise ValueError('Follow-up discovery source checksum mismatch')
    for name,digest in m['output_sha256'].items():
        if sha(out/name)!=digest:
            raise ValueError('Follow-up output checksum mismatch')
    base=ROOT/m['baseline_directory']
    if sha(base/'manifest.json')!=m['baseline_manifest_sha256'] or sha(base/'records.jsonl')!=m['baseline_records_sha256']:
        raise ValueError('Follow-up baseline changed')
    companies={c['company_id']:c for c in json.loads((base/'cohort.json').read_text())['companies']}
    new=[]
    for o in m['archive_observations']:
        if sha(out/o['file'])!=o['sha256'] or o['sha256']!=o['archive_capture']['payload_sha256']:
            raise ValueError('Follow-up archive payload mismatch')
        when=parsedate_to_datetime(o['memento_datetime']).astimezone(timezone.utc)
        if when.strftime('%Y-%m-%dT%H:%M:%SZ')!=o['snapshot_at']:
            raise ValueError('Follow-up capture clock mismatch')
        batch=normalize(json.loads((out/o['file']).read_text()),companies[o['company_id']],{'type':o['board_type']},
            o['source_url'],o['observed_at'],o['snapshot_at'],o['archive_capture'])
        if len(batch)!=o['count']:
            raise ValueError('Follow-up archive count mismatch')
        new.extend(batch)
    if new!=records(out/'job-records.jsonl') or len(new)!=m['additional_job_observations']:
        raise ValueError('Follow-up normalized replay mismatch')
    merged=records(base/'records.jsonl')+new
    if len({r['record_id'] for r in merged})!=len(merged):
        raise ValueError('Repeated follow-up job observation')
    run=run_trend_pipeline(merged)
    if [s.as_dict() for s in run.bundle.series]!=json.loads((out/'signals/series.json').read_text()) or run.coverage!=json.loads((out/'signals/coverage.json').read_text()):
        raise ValueError('Follow-up feature replay mismatch')
    if to_payload(run.signals)!=records(out/'signals/trend_signals.jsonl'):
        raise ValueError('Follow-up scored signal replay mismatch')
    comparisons=[]
    old=records(base/'records.jsonl')
    for o in m['archive_observations']:
        prior=[r for r in new if r['company_id']==o['company_id'] and r['metadata']['source_snapshot_at']==o['snapshot_at']]
        candidates=[r for r in old if r['company_id']==o['company_id']]
        latest_at=max(r['metadata']['source_snapshot_at'] for r in candidates)
        latest=[r for r in candidates if r['metadata']['source_snapshot_at']==latest_at]
        comparisons.append({'company_id':o['company_id'],'baseline_at':o['snapshot_at'],'latest_at':latest_at,**comparison(prior,latest)})
    return {'status':'offline_replay_verified','additional_job_observations':len(new),
        'merged_job_observations':len(merged),'comparisons':comparisons,
        'scope':'Additional snapshots extend existing company history; they do not increase the number of companies with historical coverage or establish completed hires.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['collect','replay'])
    parser.add_argument('--out',type=Path,default=ROOT/'evaluation/cohort-archive-followup')
    args=parser.parse_args()
    print(json.dumps(collect(args.out) if args.action=='collect' else replay(args.out),indent=2))
