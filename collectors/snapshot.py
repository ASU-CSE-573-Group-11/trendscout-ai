"""Freeze and replay Sueda's documentary collection without network access on replay."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from collectors.cohort import load_cohort, load_named_sources, included_companies
from collectors.http import FetchError, fetch_text
from collectors.pipeline import run_sueda_collection, write_collection_bundle
from collectors.records import utc_now, validate_records


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(manifest, directory):
    feeds, company_feeds = {}, {}
    for entry in manifest['sources']:
        if entry['status']!='fetched':
            continue
        path=directory/entry['file']
        if digest(path)!=entry['sha256']:
            raise ValueError('cached feed checksum mismatch: '+entry['source_id'])
        (company_feeds if entry['kind']=='company' else feeds)[entry['key']]=path.read_text()
    result=run_sueda_collection(live=False,feed_bodies=feeds,company_feed_bodies=company_feeds,
        cohort_path=directory/'cohort.json',sources_path=directory/'named_sources.json')
    for record in result['accepted']:
        record['observed_at']=manifest['observed_at']
        record['metadata']['collection_snapshot']=manifest['observed_at']
    result['stats']['live']=True
    result['stats']['mode']='frozen_feed_snapshot'
    by_id={s['source_id']:s for s in manifest['sources']}
    for coverage in result['coverage']:
        source=by_id.get(coverage['source_id'])
        if source and source['status']=='unavailable':
            coverage.update(status='unavailable',detail=source['detail'])
    return result


def collect(directory, overrides_path=None):
    if directory.exists():
        raise ValueError('refusing to overwrite snapshot')
    directory.mkdir(parents=True)
    (directory/'sources').mkdir()
    cohort,sources=load_cohort(),load_named_sources()
    overrides=json.loads(overrides_path.read_text()) if overrides_path else {}
    endpoints=overrides.get('endpoints',{})
    for kind in ['news','public_voices']:
        for source in sources.get(kind,[]):
            source['rss_url']=endpoints.get(source['source_id'],source['rss_url'])
    for company in cohort['companies']:
        company['rss_url']=endpoints.get('company:'+company['company_id'],company.get('rss_url'))
    if overrides:
        (directory/'endpoint-revision.json').write_text(json.dumps(overrides,indent=2)+'\n')
    for name,value in [('cohort.json',cohort),('named_sources.json',sources)]:
        (directory/name).write_text(json.dumps(value,indent=2)+'\n')
    entries=[]
    observed=utc_now()
    inputs=[(kind,s['source_id'],s['source_id'],s['rss_url'])
            for kind in ['news','public_voices'] for s in sources.get(kind,[])]
    inputs += [('company','company:'+c['company_id'],c['company_id'],c['rss_url'])
               for c in included_companies(cohort) if c.get('rss_url')]
    for index,(kind,source_id,key,url) in enumerate(inputs):
        entry={'kind':kind,'source_id':source_id,'key':key,'url':url}
        try:
            body=fetch_text(url)
            path=directory/'sources'/f'{index:02d}.xml'
            path.write_text(body,encoding='utf-8')
            entry.update(status='fetched',file=str(path.relative_to(directory)),sha256=digest(path))
        except FetchError as exc:
            entry.update(status='unavailable',detail=str(exc))
        entries.append(entry)
        print(source_id,entry['status'],flush=True)
    manifest={'version':1,'observed_at':observed,'sources':entries,
        'cohort_sha256':digest(directory/'cohort.json'),
        'named_sources_sha256':digest(directory/'named_sources.json'),
        'body_encoding':'UTF-8 decoded HTTP response text',
        'endpoint_revision':overrides,
        'scope':'Current feed window. No historical archive completeness asserted.'}
    result=normalized(manifest,directory)
    write_collection_bundle(result,directory)
    manifest['records_sha256']=digest(directory/'records.jsonl')
    manifest['record_count']=len(result['accepted'])
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def replay(directory):
    manifest=json.loads((directory/'manifest.json').read_text())
    for filename,key in [('cohort.json','cohort_sha256'),('named_sources.json','named_sources_sha256'),
                         ('records.jsonl','records_sha256')]:
        if digest(directory/filename)!=manifest[key]:
            raise ValueError('snapshot checksum mismatch: '+filename)
    result=normalized(manifest,directory)
    stored=[json.loads(line) for line in (directory/'records.jsonl').read_text().splitlines()]
    if stored!=result['accepted'] or validate_records(stored):
        raise ValueError('replayed records differ from frozen records')
    return {'status':'replay_verified','records':len(stored),'sources':len(manifest['sources'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['collect','replay'])
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--overrides',type=Path,help='Documented current endpoint revision; frozen cohort identities are preserved.')
    args=parser.parse_args()
    result=collect(args.directory,args.overrides) if args.action=='collect' else replay(args.directory)
    print(json.dumps({k:v for k,v in result.items() if k!='sources'},indent=2))


if __name__=='__main__':
    main()
