"""Collect and replay default-branch history for the complete frozen cohort.

Historical commit counts are reconstructed, not historical repository counters
or hiring measurements. Missing/failed repositories never become zero weeks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from collectors.common import CollectorError
from collectors.records import utc_now, validate_records
from collectors.sources import GitHubCollector, snapshot_header
from evaluation.collect_mixed_corpus import weekly_snapshots
from evaluation.real_round import ROOT
from signals.pipeline import run_trend_pipeline, write_trend_bundle
from signals.contract import to_payload


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GitHubCLIClient:
    """Use the authenticated CLI without exporting or persisting credentials."""
    def get(self, url, *, params=None):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'api.github.com':
            raise CollectorError('Only the public GitHub API is supported')
        command = ['gh', 'api', '--method', 'GET', parsed.path]
        for key, value in (params or {}).items():
            command.extend(['-f', f'{key}={value}'])
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode:
            # Do not persist CLI diagnostics that could include account details.
            raise CollectorError('GitHub API request failed; repository history unavailable')
        return json.loads(result.stdout)


def collect(out, cohort_path=ROOT/'data/registry/cohort.json', reuse=None, overrides=None):
    if out.exists():
        raise ValueError('Refusing to overwrite frozen history')
    out.mkdir(parents=True)
    (out/'sources').mkdir()
    (out/'cohort.json').write_bytes(cohort_path.read_bytes())
    observed = utc_now()
    coverage, records = [], []
    cohort = json.loads(cohort_path.read_text())
    revisions = json.loads(overrides.read_text()) if overrides else {}
    if overrides:
        (out/'repository-revisions.json').write_bytes(overrides.read_bytes())
    cached = {}
    if reuse:
        replay(reuse)
        previous = json.loads((reuse/'manifest.json').read_text())
        cached = {(c['company_id'],r['repository']):r for c in previous['companies']
                  for r in c['repositories'] if r['status']=='collected'}
    for company in cohort['companies']:
        if company['status'] != 'included':
            continue
        cid = company['company_id']
        entry = {'company_id':cid, 'repositories':[], 'status':'unavailable', 'weekly_records':0}
        for url in revisions.get(cid,{}).get('github_repos',company.get('github_repos', [])):
            target = urlparse(url).path.strip('/')
            try:
                source = cached.get((cid,target))
                if source:
                    snapshot = json.loads((reuse/source['file']).read_text())
                else:
                    snapshot = GitHubCollector(window_days=63).collect(GitHubCLIClient(),
                        snapshot_header('github', target, cid, company['name'], observed))
                weekly = list(weekly_snapshots(snapshot))
                if len(weekly) != 8 or validate_records(weekly):
                    raise ValueError('Invalid historical records')
                filename = 'sources/'+cid+'-'+target.replace('/', '--')+'.json'
                path = out/filename
                path.write_text(json.dumps(snapshot, ensure_ascii=False)+'\n')
                records.extend(weekly)
                entry['repositories'].append({'repository':target, 'status':'collected',
                    'file':filename, 'sha256':digest(path),
                    'commit_count':len(snapshot['payload']['commits']),
                    'default_branch_sha':snapshot['coverage']['default_branch_sha']})
                entry['weekly_records'] += len(weekly)
                entry['status'] = 'collected'
            except (CollectorError, ValueError, subprocess.TimeoutExpired) as exc:
                entry['repositories'].append({'repository':target,'status':'unavailable',
                    'reason':str(exc)})
        coverage.append(entry)
        print(cid, entry['status'], entry['weekly_records'], flush=True)
    (out/'records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    run = run_trend_pipeline(records)
    write_trend_bundle(run, out/'signals')
    manifest = {'observed_at':observed, 'cohort_sha256':digest(out/'cohort.json'),
        'repository_revisions_sha256':digest(out/'repository-revisions.json') if overrides else None,
        'reused_source_directory':str(reuse) if reuse else None,
        'reuse_policy':'Reused snapshots retain their original observation times and payloads; only unavailable/revised repositories are fetched again.',
        'scope':'Eight complete ISO weeks of default-branch commits per available frozen-cohort repository.',
        'companies':coverage,'companies_requested':len(coverage),
        'companies_collected':sum(c['status']=='collected' for c in coverage),
        'weekly_records':len(records),
        'output_sha256':{str(p.relative_to(out)):digest(p) for p in
            [out/'records.jsonl', *sorted((out/'signals').iterdir())]},
        'limits':['This is software activity, not hiring, funding or company headcount.',
            'Repository stars, forks and issues are not reconstructed historically.',
            'Default-branch commits available at collection time exclude other branches and deleted history.',
            'The frozen repository choice is preserved; a dormant repository does not imply an inactive company.',
            'No annotation attestations or participant measurements are created.']}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return {'companies_collected':manifest['companies_collected'], 'weekly_records':len(records)}


def replay(out):
    manifest = json.loads((out/'manifest.json').read_text())
    if digest(out/'cohort.json') != manifest['cohort_sha256']:
        raise ValueError('Cohort checksum mismatch')
    for filename, expected in manifest['output_sha256'].items():
        if digest(out/filename) != expected:
            raise ValueError('Historical output checksum mismatch')
    cohort = json.loads((out/'cohort.json').read_text())
    revisions = {}
    if manifest.get('repository_revisions_sha256'):
        if digest(out/'repository-revisions.json') != manifest['repository_revisions_sha256']:
            raise ValueError('Repository revision checksum mismatch')
        revisions = json.loads((out/'repository-revisions.json').read_text())
    company_by_id = {c['company_id']:c for c in cohort['companies']}
    expected_companies = [c['company_id'] for c in cohort['companies'] if c['status']=='included']
    if [c['company_id'] for c in manifest['companies']] != expected_companies:
        raise ValueError('Incomplete or changed cohort coverage accounting')
    records = []
    collected = 0
    for company in manifest['companies']:
        expected_targets = [urlparse(url).path.strip('/') for url in
            revisions.get(company['company_id'],{}).get('github_repos',company_by_id[company['company_id']].get('github_repos',[]))]
        if [r['repository'] for r in company['repositories']] != expected_targets:
            raise ValueError('Historical repository selection mismatch')
        count = 0
        for repository in company['repositories']:
            if repository['status'] != 'collected':
                continue
            path = out/repository['file']
            if digest(path) != repository['sha256']:
                raise ValueError('Historical source checksum mismatch')
            snapshot = json.loads(path.read_text())
            if snapshot['company_id'] != company['company_id'] or snapshot['target'] != repository['repository']:
                raise ValueError('Historical source identity mismatch')
            rebuilt = list(weekly_snapshots(snapshot))
            records.extend(rebuilt)
            count += len(rebuilt)
        if count != company['weekly_records'] or (count > 0) != (company['status']=='collected'):
            raise ValueError('Historical company coverage mismatch')
        collected += count > 0
    stored = [json.loads(line) for line in (out/'records.jsonl').read_text().splitlines()]
    if records != stored or validate_records(records):
        raise ValueError('Historical replay mismatch')
    if manifest['weekly_records'] != len(records) or manifest['companies_collected'] != collected or manifest['companies_requested'] != len(expected_companies):
        raise ValueError('Historical coverage total mismatch')
    run = run_trend_pipeline(records)
    if [s.as_dict() for s in run.bundle.series] != json.loads((out/'signals/series.json').read_text()):
        raise ValueError('Historical feature replay mismatch')
    if run.coverage != json.loads((out/'signals/coverage.json').read_text()):
        raise ValueError('Historical signal coverage mismatch')
    if to_payload(run.signals) != [json.loads(line) for line in (out/'signals/trend_signals.jsonl').read_text().splitlines()]:
        raise ValueError('Historical scored signal replay mismatch')
    return {'status':'offline_replay_verified', 'companies_collected':collected,
        'companies_requested':len(expected_companies),'weekly_records':len(records)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['collect','replay'])
    parser.add_argument('--out', type=Path, default=ROOT/'evaluation/cohort-history')
    parser.add_argument('--reuse', type=Path)
    parser.add_argument('--repository-overrides', type=Path)
    args = parser.parse_args()
    print(json.dumps(collect(args.out,reuse=args.reuse,overrides=args.repository_overrides) if args.action=='collect' else replay(args.out),indent=2))
