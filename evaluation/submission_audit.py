"""Audit repository evidence and build a local review archive with explicit status."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collectors.records import utc_now
from evaluation.real_round import ROOT, read_json, write_json


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def dependency_inventory(root):
    inventory=[]
    for filename in ['requirements.txt','requirements-collectors.txt','requirements-interface.txt']:
        for line in (root/filename).read_text().splitlines():
            requirement=line.split('#',1)[0].strip()
            if not requirement:continue
            name=re.split(r'[\[<>=!~ ]',requirement)[0]
            try:
                record=metadata.metadata(name)
                license_name=record.get('License-Expression') or record.get('License') or ''
                if 'Apache License' in license_name and re.search(r'Version\s+2\.0',license_name):
                    license_name='Apache-2.0'
                if len(license_name)>100:license_name='See installed package license text'
                inventory.append({'requirement':requirement,'declared_in':filename,'installed':True,
                    'installed_version':metadata.version(name),'license':license_name or 'Not declared in installed metadata',
                    'evidence':'Installed distribution METADATA; inventory only, not redistribution clearance.'})
            except metadata.PackageNotFoundError:
                inventory.append({'requirement':requirement,'declared_in':filename,'installed':False,
                    'installed_version':None,'license':None,'evidence':'Optional/uninstalled dependency; upstream license review required before distribution.'})
    return inventory


def installed_inventory():
    records=[]
    for distribution in metadata.distributions():
        info=distribution.metadata
        license_name=info.get('License-Expression') or info.get('License') or None
        if license_name and 'Apache License' in license_name and re.search(r'Version\s+2\.0',license_name):
            license_name='Apache-2.0'
        if license_name and len(license_name)>100:license_name='See installed distribution license text'
        records.append({'name':info['Name'],'version':distribution.version,'license':license_name,
                        'evidence':'Installed distribution METADATA; verify upstream terms before redistribution.'})
    return sorted(records,key=lambda r:r['name'].lower())


def audit(root=ROOT):
    out=root/'evaluation/submission'
    out.mkdir(exist_ok=True)
    contribution=read_json(root/'evaluation/real/contribution-record.json')
    members=[]
    for member in contribution['members']:
        commits=[]
        for entry in member['repository_contributions']:
            commit=entry['commit']
            author=git('show','-s','--format=%an',commit)
            subject=git('show','-s','--format=%s',commit)
            changed=set(git('diff-tree','--root','--no-commit-id','--name-only','-r',commit).splitlines())
            missing=sorted(set(entry['changed_paths'])-changed)
            commits.append({'commit':commit,'recorded_author':author,'subject':subject,
                'claimed_paths_verified':not missing,'unmatched_paths':missing})
        artifacts=[]
        for entry in member.get('prepared_deliverables',[]):
            path=root/entry['path']
            artifacts.append({'path':entry['path'],'hash_matches':path.exists() and sha(path)==entry['sha256']})
        members.append({'name':member['name'],'commits':commits,'prepared_artifacts':artifacts,
            'project_account_identity':member.get('identity_verification',{'status':'not_confirmed'}),
            'ownership_basis':'docs/project-plan.md',
            'personal_annotation_and_pilot_participation':'Requires actual study records; not inferred from code authorship.'})
    write_json(out/'contribution-audit.json',{'checked_at':utc_now(),'members':members,
        'scope':'Local commit objects, recorded authors, changed paths, and artifact hashes. Identity aliases are not inferred.'})
    collection=read_json(root/'evaluation/sueda-delivery-corpus/manifest.json')
    source_inventory=[{'source_id':s['source_id'],'url':s['url'],'fetch_status':s['status'],
        'access_note':s.get('detail','Public RSS/Atom fetched and cached for local coursework.'),
        'redistribution_clearance':'not_established'} for s in collection['sources']]
    for name in ['real', 'mixed']:
        frozen=read_json(root/f'evaluation/{name}/manifest.json')
        for source in frozen['sources']:
            source_inventory.append({'source_id':f"{name}:{source['file']}",
                'url':source.get('api_url') or source.get('url'),
                'fetch_status':'frozen_source_present', 'snapshot':f'evaluation/{name}',
                'access_note':'Public source cached for the frozen study; original manifest and source checksum retained.',
                'redistribution_clearance':'not_established'})
    license_path=root/'LICENSE'
    if license_path.exists():
        license_text=license_path.read_text(encoding='utf-8',errors='replace')
        if 'MIT License' in license_text:
            team_license='MIT (LICENSE at repository root)'
        else:
            team_license='LICENSE present at repository root; see file for exact terms'
    else:
        team_license='No repository-wide LICENSE has been selected by the team.'
    write_json(out/'license-access-inventory.json',{'checked_at':utc_now(),
        'team_code_distribution_license':team_license,
        'dependencies':dependency_inventory(root),'installed_environment':installed_inventory(),
        'documentary_sources':source_inventory,
        'distribution_scope':('Local coursework review archive under the team MIT LICENSE for original team code. '
            'Cached publisher bodies and third-party dependency packages retain upstream rights; '
            'redistribution_clearance for documentary sources remains not_established until publisher terms are cleared.'),
        'live_repository_access':'access-review.json'})
    pilot=read_json(root/'evaluation/real/trust-pilot.json')
    response_path=root/'evaluation/real/pilot-session/responses.json'
    responses=read_json(response_path)['responses'] if response_path.exists() else []
    from evaluation.pilot_analysis import summarize as summarize_pilot
    collection=summarize_pilot(root/'evaluation/real')
    errors=[{'member':m['name'],'commit':c['commit'],'paths':c['unmatched_paths']}
            for m in members for c in m['commits'] if not c['claimed_paths_verified']]
    stale=[a['path'] for m in members for a in m['prepared_artifacts'] if not a['hash_matches']]
    remaining=[]
    if collection['remaining_tasks']:
        remaining.append(f"{collection['remaining_tasks']} additional actual participant task responses")
    if not collection['task_key_adjudication_complete']:
        remaining.append('Independent task-key review and final pilot correctness grading')
    # Annotation complete for Sueda/Mehmet when direct agreement artifacts exist.
    agreement_path=root/'evaluation/independent-review/real/agreement.json'
    annotation_done=False
    if agreement_path.exists():
        agreement=read_json(agreement_path)
        annotation_done=(
            agreement.get('status')=='computed_from_direct_source_reviews'
            or (agreement.get('method') and agreement.get('results')
                and all(kind in agreement['results'] for kind in ('entities','relations')))
        )
    if not annotation_done:
        remaining.append('Independent paired annotation and final adjudication')
    if not license_path.exists():
        remaining.append('Team code license selection and source redistribution review')
    else:
        remaining.append('Publisher redistribution clearance for cached documentary sources (team MIT LICENSE covers original team code only)')
    remaining.append('Verify or enable server-side branch protection under an eligible GitHub plan')
    result={'status':'local_review_package','checked_at':utc_now(),
        'contribution_commit_path_mismatches':errors,'stale_contribution_artifacts':stale,
        'consent_reports':len(pilot['participants']),'recorded_pilot_responses':len(responses),
        'scored_pilot_task_results':len(pilot['task_results']),
        'pilot_collection_complete':collection['collection_complete'],
        'confirmed_project_account_mappings':sum(m['project_account_identity'].get('status')=='project_account_mapping_confirmed' for m in members),
        'remaining_requirements':remaining,
        'complete_research_submission':False}
    write_json(out/'submission-status.json',result)
    return result


def build(root=ROOT, destination=None):
    status=audit(root)
    if status['contribution_commit_path_mismatches'] or status['stale_contribution_artifacts']:
        raise ValueError('resolve contribution evidence mismatches before packaging')
    destination=destination or root/'artifacts/submission-review.zip'
    if destination.exists():
        raise ValueError('refusing to overwrite existing review archive')
    destination.parent.mkdir(parents=True,exist_ok=True)
    directories=['collectors','data/registry','docs','evaluation','graph','interface','ontology','retrieval','schemas','scripts','signals','tests','.github','assets']
    paths=[]
    for directory in directories:
        paths += [p for p in (root/directory).rglob('*') if p.is_file() and not p.is_symlink()
                  and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts and p.suffix not in {'.pyc','.pem','.key'}]
    paths += [root/name for name in ['README.md','pyproject.toml','requirements.txt','requirements-collectors.txt',
                                    'requirements-interface.txt','docker-compose.yml','.gitignore','.env.example']]
    files={str(p.relative_to(root)):sha(p) for p in sorted(set(paths))}
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(paths)):
            archive.write(path,str(path.relative_to(root)))
        archive.writestr('REVIEW-MANIFEST.json',json.dumps({'status':status,'files':files},indent=2))
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:raise ValueError('archive integrity failure')
        for name,digest in files.items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest:
                raise ValueError('packaged file checksum mismatch: '+name)
    return {'archive':str(destination),'files':len(files),'sha256':sha(destination),'complete_research_submission':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['audit','build'])
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    print(json.dumps(audit() if args.action=='audit' else build(destination=args.out),indent=2))
