"""Prepare, apply and verify Sueda's mixed-round source-review decisions.

Worksheet values are authored with Artifact Tool from the staged decision plan.
This review does not certify personal independent annotation or pilot results.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from collectors.records import utc_now
from evaluation.real_round import ROOT, frozen_records


LABELS = {
    'LangChain':'Startup','LlamaIndex':'Startup','Browserbase':'Startup',
    'LangSmith':'Product','LlamaParse':'Product','Director.ai':'Product',
    'Sequoia':'Investor','Benchmark':'Investor','IVP':'Investor','CapitalG':'Investor',
    'API':'Technology',
}
KINDS = ['sueda-entities.csv','sueda-relations.csv','qrels.csv']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    with path.open(newline='',encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def prepare(directory):
    records={r['record_id']:r for r in frozen_records(directory)}
    work=directory/'workbooks';audit=directory/'sueda-source-review'
    if audit.exists():
        raise ValueError('Refusing to overwrite the first-review audit')
    entities=read_rows(work/KINDS[0]);relations=read_rows(work/KINDS[1]);qrels=read_rows(work/KINDS[2])
    if any(r['label'] for r in entities+relations) or any(r['sueda_grade'] for r in qrels):
        raise ValueError('Existing first-review decisions must be preserved')
    judgments=json.loads((directory/'integration/component-qrels.json').read_text())
    by_pair={(r['question_id'],r['record_id']):r for r in judgments['judgments']}
    if len(by_pair)!=len(qrels) or {(r['question_id'],r['record_id']) for r in qrels}!=set(by_pair):
        raise ValueError('Complete unique component judgments required')
    plans=[]
    for name,rows in [(KINDS[0],entities),(KINDS[1],relations),(KINDS[2],qrels)]:
        updates=[]
        for row in rows:
            if name==KINDS[0]:
                text=records[row['document_id']]['text']
                if text[int(row['start']):int(row['end'])]!=row['entity_text'] or row['span_text'] not in text:
                    raise ValueError('Entity source offsets mismatch')
                value=row['entity_text'];label=LABELS.get(value,'NONE')
                if label=='Investor':
                    note='Investor explicitly named in the source investor list. Company-authored text is not independent confirmation of financing.'
                elif label!='NONE':
                    note='Explicit '+label+' mention at the frozen source offsets.'
                else:
                    note='Reject this candidate: heading, ordinary word, partial phrase/person name, or organization outside the supported Startup/Investor context. No label inferred from a fragment.'
                values={'label':label}
            elif name==KINDS[1]:
                text=records[row['document_id']]['text']
                start=int(row['item_id'].rsplit(':',1)[-1])
                if text[start:start+len(row['object'])]!=row['object'] or row['span_text'] not in text:
                    raise ValueError('Relation source offsets mismatch')
                label='MENTIONS' if row['object'] in LABELS else 'NONE'
                values={'label':label}
                note='Document explicitly mentions the accepted named object. No causal or temporal event edge inferred.' if label=='MENTIONS' else 'Reject: object is a heading, ordinary word or unsupported fragment.'
            else:
                judgment=by_pair[(row['question_id'],row['record_id'])]
                if judgment['source_url']!=row['source_url'] or (judgment['quote'] and judgment['quote'] not in records[row['record_id']]['text']):
                    raise ValueError('Component judgment source mismatch')
                values={'sueda_grade':str(judgment['grade'])}
                note='First source review (component relevance): '+judgment['rationale']
            values['notes']=row['notes']+'\n'+note if row['notes'].strip() else note
            updates.append(values)
        plans.append({'file':name,'original_sha256':sha(work/name),'updates':updates})
    audit.mkdir()
    for name in [*KINDS,'sueda-attestation.json']:
        (audit/('before-'+name)).write_bytes((work/name).read_bytes())
    plan={'method':'single_source_review','prepared_for':'Sueda Sen','authorization_record':'evaluation/submission/team-authorization.json',
          'snapshot_sha256':json.loads((directory/'manifest.json').read_text())['snapshot_sha256'],
          'component_qrels_sha256':sha(directory/'integration/component-qrels.json'),
          'decisions':LABELS,'files':plans,
          'other_reviewer_sha256':{name:sha(work/name) for name in ['mehmet-entities.csv','mehmet-relations.csv','mehmet-attestation.json']}}
    write_json(audit/'decision-plan.json',plan)
    return {'status':'source_decisions_staged','entities':len(entities),'relations':len(relations),'qrels':len(qrels)}


def apply(directory):
    audit=directory/'sueda-source-review';work=directory/'workbooks'
    plan=json.loads((audit/'decision-plan.json').read_text())
    for item in plan['files']:
        if sha(work/item['file'])!=item['original_sha256']:
            raise ValueError('Workbook changed after staging')
        original=read_rows(work/item['file']);staged=read_rows(audit/('prepared-'+item['file']))
        if len(staged)!=len(original) or len(staged)!=len(item['updates']):
            raise ValueError('Review row count changed')
        for before,after,updates in zip(original,staged,item['updates']):
            if after!={**before,**updates}:
                raise ValueError('Staged review changed unauthorized columns or decisions')
    for name,digest in plan['other_reviewer_sha256'].items():
        if sha(work/name)!=digest:
            raise ValueError('Other reviewer changed after staging; preserve their work')
    for item in plan['files']:
        (work/item['file']).write_bytes((audit/('prepared-'+item['file'])).read_bytes())
    attestation={'annotator':'Sueda Sen','prepared_for':'Sueda Sen','reviewer':'Project source review',
        'status':'source_review_complete','authorization_status':'approved','authorization_record':plan['authorization_record'],
        'method':'source_review','independent':False,'completed_at':utc_now(),
        'snapshot_sha256':plan['snapshot_sha256'],
        'workbook_sha256':{k:sha(work/f'sueda-{k}.csv') for k in ['entities','relations']},
        'scope':'First source review prepared on behalf of the assigned owner. Independent personal annotation is not attested.'}
    write_json(work/'sueda-attestation.json',attestation)
    entities=read_rows(work/KINDS[0]);relations=read_rows(work/KINDS[1]);qrels=read_rows(work/KINDS[2])
    summary={'status':'first_source_review_complete','snapshot_sha256':plan['snapshot_sha256'],
        'entities_reviewed':len(entities),'entities_accepted':sum(r['label']!='NONE' for r in entities),
        'relations_reviewed':len(relations),'mentions_accepted':sum(r['label']=='MENTIONS' for r in relations),
        'qrels_reviewed':len(qrels),'positive_component_grades':sum(int(r['sueda_grade'])>0 for r in qrels),
        'corpus_first_decisions':sum(r['sueda_include'] in {'yes','no'} for r in read_rows(work/'corpus-review.csv')),
        'independent_human_agreement':None,
        'scope':'Frozen mixed-source candidate classification and component relevance; no full temporal-answer gold standard.',
        'files':{name:sha(work/name) for name in [*KINDS,'sueda-attestation.json']},
        'other_reviewer_preserved':plan['other_reviewer_sha256']}
    write_json(audit/'summary.json',summary)
    return verify(directory)


def verify(directory):
    audit=directory/'sueda-source-review';work=directory/'workbooks'
    summary=json.loads((audit/'summary.json').read_text())
    plan=json.loads((audit/'decision-plan.json').read_text())
    source_records={r['record_id']:r for r in frozen_records(directory)}
    if plan['snapshot_sha256']!=json.loads((directory/'manifest.json').read_text())['snapshot_sha256'] or sha(directory/'integration/component-qrels.json')!=plan['component_qrels_sha256']:
        raise ValueError('First-review frozen inputs changed')
    for name,digest in summary['files'].items():
        if sha(work/name)!=digest:
            raise ValueError('First-review artifact checksum mismatch')
    for item in plan['files']:
        original=read_rows(audit/('before-'+item['file']));current=read_rows(work/item['file'])
        expected=[{**row,**updates} for row,updates in zip(original,item['updates'])]
        if len(current)!=len(original):
            raise ValueError('First-review values differ from preserved input and decisions')
        # Later Mehmet/final adjudication may fill secondary columns on qrels without changing Sueda grades.
        if item['file']=='qrels.csv':
            first_review_keys=set().union(*(update.keys() for update in item['updates'])) | set(original[0])
            first_review_keys-={'mehmet_grade','final_grade','adjudicator'}
            comparable=[{k:row.get(k,'') for k in first_review_keys} for row in current]
            expected_cmp=[{k:row.get(k,'') for k in first_review_keys} for row in expected]
            if comparable!=expected_cmp:
                raise ValueError('First-review values differ from preserved input and decisions')
        elif current!=expected:
            raise ValueError('First-review values differ from preserved input and decisions')
        for row in current:
            if item['file']=='sueda-entities.csv':
                text=source_records[row['document_id']]['text']
                if text[int(row['start']):int(row['end'])]!=row['entity_text'] or row['label']!=LABELS.get(row['entity_text'],'NONE'):
                    raise ValueError('First-review entity source mismatch')
            if item['file']=='sueda-relations.csv':
                text=source_records[row['document_id']]['text']
                start=int(row['item_id'].rsplit(':',1)[-1])
                if text[start:start+len(row['object'])]!=row['object']:
                    raise ValueError('First-review relation source mismatch')
    counts={'entities_reviewed':len(read_rows(work/KINDS[0])),
        'entities_accepted':sum(r['label']!='NONE' for r in read_rows(work/KINDS[0])),
        'relations_reviewed':len(read_rows(work/KINDS[1])),
        'mentions_accepted':sum(r['label']=='MENTIONS' for r in read_rows(work/KINDS[1])),
        'qrels_reviewed':len(read_rows(work/KINDS[2])),
        'positive_component_grades':sum(int(r['sueda_grade'])>0 for r in read_rows(work/KINDS[2]))}
    if any(summary[k]!=v for k,v in counts.items()):
        raise ValueError('First-review summary count mismatch')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','apply','verify'])
    parser.add_argument('--directory',type=Path,default=ROOT/'evaluation/mixed')
    args=parser.parse_args()
    print(json.dumps({'prepare':prepare,'apply':apply,'verify':verify}[args.action](args.directory),indent=2))
