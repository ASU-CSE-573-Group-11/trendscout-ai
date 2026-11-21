"""Normalize verified official-board sources and available in-window archives."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from collectors.common import job_fields, plain_text
from collectors.records import make_record, parse_datetime, utc_now, validate_records
from evaluation.real_round import ROOT
from signals.pipeline import run_trend_pipeline, write_trend_bundle
from signals.contract import to_payload


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(payload, company, board, source_url, observed_at, snapshot_at, archive=None):
    observed_at = parse_datetime(observed_at)
    snapshot_at = parse_datetime(snapshot_at)
    jobs = payload.get('jobs')
    if not isinstance(jobs,list):
        raise ValueError('Complete job array required')
    if board['type']=='greenhouse' and payload.get('meta',{}).get('total',len(jobs)) != len(jobs):
        raise ValueError('Incomplete Greenhouse board response')
    ids, records = set(), []
    for job in jobs:
        if job.get('isListed',True) is False:
            continue
        raw_id = job.get('id')
        if type(raw_id) not in {str,int}:
            raise ValueError('Missing or invalid posting identity')
        jid = str(raw_id)
        if not jid or jid in ids:
            raise ValueError('Missing or duplicate posting identity')
        ids.add(jid)
        title = job.get('title')
        if not isinstance(title,str) or not title.strip():
            raise ValueError('Missing job title')
        original = job.get('jobUrl') or job.get('absolute_url')
        if not isinstance(original,str) or not original.startswith('https://'):
            raise ValueError('Missing public posting URL')
        # Greenhouse's ordinary list endpoint omits descriptions and its
        # updated_at is not a publication timestamp.
        text = job.get('descriptionPlain') or plain_text(job.get('descriptionHtml') or job.get('content'))
        text = text or title
        published = job.get('publishedAt') if board['type']=='ashby' else None
        if published and parse_datetime(published)>parse_datetime(snapshot_at):
            raise ValueError('Publication timestamp is after board observation')
        fields = job_fields(title,text)
        fields.update(source_record_id=f"{board['type']}:{company['company_id']}:{jid}",
            source_snapshot_at=snapshot_at, original_job_url=original,
            source_control_group='company:'+company['company_id'],
            collector='cohort_job_board', synthetic=False,
            description_available=(text!=title),
            publication_caveat='Current publication does not establish historical listing availability; Greenhouse update times are not publication dates.')
        if archive:
            fields['archive_capture']=archive
        r = make_record(source_type='job',source_url=source_url,title=title,text=text,
            publisher=company['name'],startup_name=company['name'],company_id=company['company_id'],
            observed_at=observed_at,event_at=snapshot_at,published_at=published,
            event_type='job_board_observation',collector_version='cohort-jobs/1.0',metadata=fields)
        r['record_id']=f"job-board:{company['company_id']}:{jid}:"+hashlib.sha256((source_url+snapshot_at).encode()).hexdigest()[:16]
        records.append(r)
    if validate_records(records):
        raise ValueError('Invalid board records')
    return records


def comparison(before,after):
    left={r['metadata']['source_record_id'] for r in before}
    right={r['metadata']['source_record_id'] for r in after}
    return {'baseline_listed':len(left),'latest_listed':len(right),
        'net_posting_change':len(right)-len(left),
        'newly_observed':len(right-left),'no_longer_observed':len(left-right),'retained':len(left&right)}


def collect(out, audit):
    if out.exists():
        raise ValueError('Refusing to overwrite job history')
    out.mkdir(parents=True)
    (out/'sources').mkdir()
    cohort=json.loads((ROOT/'data/registry/cohort.json').read_text())
    (out/'cohort.json').write_text(json.dumps(cohort,indent=2)+'\n')
    companies={c['company_id']:c for c in cohort['companies'] if c['status']=='included'}
    audit_data=json.loads((audit/'board-audit.json').read_text())
    records,coverage,raws=[],[],[]
    for company_entry in audit_data['companies']:
        cid=company_entry['company_id'];company=companies[cid]
        entry={'company_id':cid,'boards':[],'current_listed':None,'historical_in_window':False}
        for index,board in enumerate(company_entry['boards']):
            b={'type':board['type'],'slug':board['slug'],'link_evidence':board['link_evidence'],
                'api_url':board['api_url'],'observations':[],
                'out_of_window_captures':[c['timestamp'] for c in board.get('captures',[]) if c['timestamp']<'20251101000000'],
                'archive_lookup_status':'completed' if 'captures' in board else 'unavailable'}
            if board.get('current_http_status')!=200:
                b['status']='current_unavailable';entry['boards'].append(b);continue
            source_path=audit/board['current_file']
            if sha(source_path)!=board['current_sha256']:
                raise ValueError('Source audit checksum changed')
            name=f'sources/{cid}-{index}-current.json'
            (out/name).write_bytes(source_path.read_bytes())
            now=board['checked_at']
            current=normalize(json.loads(source_path.read_text()),company,board,board['api_url'],now,now)
            records.extend(current)
            raws.append({'file':name,'sha256':sha(out/name),'source_url':board['api_url']})
            b['observations'].append({'file':name,'source_url':board['api_url'],'snapshot_at':now,'observed_at':now,'count':len(current)})
            entry['current_listed']=(entry['current_listed'] or 0)+len(current)
            for capture in board.get('captures',[]):
                if not '20251101000000' <= capture['timestamp'] <= '20261121235959':
                    continue
                url=f"https://web.archive.org/web/{capture['timestamp']}id_/{board['api_url']}"
                try:
                    response=requests.get(url,timeout=40,headers={'User-Agent':'TrendScout-research/1.0'})
                    response.raise_for_status()
                    when=parsedate_to_datetime(response.headers['Memento-Datetime']).astimezone(timezone.utc)
                    if when.strftime('%Y%m%d%H%M%S')!=capture['timestamp']:
                        raise ValueError('Archive timestamp mismatch')
                    name=f"sources/{cid}-{index}-{capture['timestamp']}.json"
                    (out/name).write_bytes(response.content)
                    instant=when.isoformat().replace('+00:00','Z')
                    archive={'verified':True,'captured_at':instant,'url':response.url,'payload_sha256':sha(out/name),
                        'verification':'CDX timestamp equals Memento-Datetime; payload retained and hashed.'}
                    retrieved=utc_now()
                    prior=normalize(response.json(),company,board,response.url,retrieved,instant,archive)
                    records.extend(prior)
                    raws.append({'file':name,'sha256':sha(out/name),'source_url':response.url})
                    b['observations'].append({'file':name,'source_url':response.url,'snapshot_at':instant,
                        'observed_at':retrieved,'archive_capture':archive,'count':len(prior),
                        'memento_datetime':response.headers['Memento-Datetime'],'cdx_timestamp':capture['timestamp']})
                    b.setdefault('comparisons',[]).append({'baseline_at':instant,'latest_at':now,**comparison(prior,current)})
                    entry['historical_in_window']=True
                except (requests.RequestException,ValueError,KeyError) as exc:
                    b.setdefault('failed_captures',[]).append({'timestamp':capture['timestamp'],'reason':type(exc).__name__})
            b['status']='historical_comparison_available' if b.get('comparisons') else 'current_only'
            entry['boards'].append(b)
        coverage.append(entry)
        print(cid,entry['current_listed'],entry['historical_in_window'],flush=True)
    if set(companies)!={c['company_id'] for c in coverage}:
        raise ValueError('Cohort coverage accounting incomplete')
    (out/'records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    write_trend_bundle(run_trend_pipeline(records),out/'signals')
    manifest={'companies':coverage,'sources':raws,'cohort_sha256':sha(out/'cohort.json'),
        'study_window':{'start':'2025-11-01','end':'2026-11-21'},
        'audit_directory':str(audit.relative_to(ROOT)),
        'audit_sha256':{name:sha(audit/name) for name in ['careers-discovery.json','board-audit.json']},
        'record_count':len(records),
        'output_sha256':{str(p.relative_to(out)):sha(p) for p in [out/'records.jsonl',*sorted((out/'signals').iterdir())]},
        'limits':['A missing board mapping/capture means unknown coverage, not zero postings.',
            'Parent-company boards are not attributed wholesale to a cohort subsidiary.',
            'Publication dates do not establish historical listing stock or completed hires.',
            'Two captured observations do not establish a weekly hiring trajectory.',
            'Official board-link discovery is separate from career-page or corporate-identity verification.']}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return replay(out)


def replay(out):
    manifest=json.loads((out/'manifest.json').read_text())
    if sha(out/'cohort.json')!=manifest['cohort_sha256']:
        raise ValueError('Job cohort checksum mismatch')
    for source in manifest['sources']:
        if sha(out/source['file'])!=source['sha256']:
            raise ValueError('Job source checksum mismatch')
    for name,digest in manifest['output_sha256'].items():
        if sha(out/name)!=digest:
            raise ValueError('Job output checksum mismatch')
    audit=ROOT/manifest['audit_directory']
    for name,digest in manifest['audit_sha256'].items():
        if sha(audit/name)!=digest:
            raise ValueError('Job source audit checksum mismatch')
    discovery=json.loads((audit/'careers-discovery.json').read_text())
    for source in discovery['sources']:
        if source.get('file') and sha(audit/source['file'])!=source['sha256']:
            raise ValueError('Official career-page checksum mismatch')
    boards=json.loads((audit/'board-audit.json').read_text())
    for c in boards['companies']:
        for b in c['boards']:
            for prefix in ['current','cdx']:
                if b.get(prefix+'_file') and sha(audit/b[prefix+'_file'])!=b[prefix+'_sha256']:
                    raise ValueError('Board audit source checksum mismatch')
    companies={c['company_id']:c for c in json.loads((out/'cohort.json').read_text())['companies'] if c['status']=='included'}
    if len(manifest['companies'])!=len(companies) or {c['company_id'] for c in manifest['companies']}!=set(companies):
        raise ValueError('Incomplete job cohort accounting')
    records=[]
    for c in manifest['companies']:
        for b in c['boards']:
            observations=[]
            for observation in b['observations']:
                archive=observation.get('archive_capture')
                if archive:
                    if archive['payload_sha256']!=sha(out/observation['file']) or archive['url']!=observation['source_url'] or archive['captured_at']!=observation['snapshot_at']:
                        raise ValueError('Archive payload provenance mismatch')
                    capture=parsedate_to_datetime(observation['memento_datetime']).astimezone(timezone.utc)
                    if capture.strftime('%Y%m%d%H%M%S')!=observation['cdx_timestamp'] or parse_datetime(capture.isoformat())!=observation['snapshot_at']:
                        raise ValueError('Archive capture clock mismatch')
                rebuilt=normalize(json.loads((out/observation['file']).read_text()),companies[c['company_id']],b,
                    observation['source_url'],observation['observed_at'],observation['snapshot_at'],observation.get('archive_capture'))
                if len(rebuilt)!=observation['count']:
                    raise ValueError('Job observation count mismatch')
                records.extend(rebuilt);observations.append(rebuilt)
            if b.get('comparisons'):
                if [comparison(prior,observations[0]) for prior in observations[1:]]!=[
                    {k:v for k,v in comp.items() if k not in {'baseline_at','latest_at'}} for comp in b['comparisons']]:
                    raise ValueError('Job comparison mismatch')
    stored=[json.loads(line) for line in (out/'records.jsonl').read_text().splitlines()]
    if records!=stored or len(records)!=manifest['record_count'] or validate_records(records):
        raise ValueError('Job history replay mismatch')
    run=run_trend_pipeline(records)
    if [s.as_dict() for s in run.bundle.series]!=json.loads((out/'signals/series.json').read_text()):
        raise ValueError('Job feature replay mismatch')
    if run.coverage!=json.loads((out/'signals/coverage.json').read_text()):
        raise ValueError('Job signal coverage mismatch')
    if to_payload(run.signals)!=[json.loads(line) for line in (out/'signals/trend_signals.jsonl').read_text().splitlines()]:
        raise ValueError('Job scored signal replay mismatch')
    return {'status':'offline_replay_verified','companies_requested':len(companies),
        'current_boards':sum(c['current_listed'] is not None for c in manifest['companies']),
        'historical_companies':sum(c['historical_in_window'] for c in manifest['companies']),
        'job_observations':len(records)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['collect','replay'])
    parser.add_argument('--out',type=Path,default=ROOT/'evaluation/cohort-job-history')
    parser.add_argument('--audit',type=Path,default=ROOT/'evaluation/cohort-source-audit')
    args=parser.parse_args()
    print(json.dumps(collect(args.out,args.audit) if args.action=='collect' else replay(args.out),indent=2))
