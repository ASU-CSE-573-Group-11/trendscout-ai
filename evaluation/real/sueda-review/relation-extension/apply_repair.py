"""Apply the Artifact Tool-prepared, narrowly verified source-passage repair once."""
import csv
import hashlib
import json
from pathlib import Path
from collectors.records import utc_now

base=Path('evaluation/real');audit=base/'sueda-review/relation-extension'
plan=json.loads((audit/'repair-plan.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
path=base/'workbooks/sueda-relations.csv';prepared=audit/'prepared-sueda-relations.csv'
if sha(path)!=plan['input_sha256']:raise ValueError('Workbook changed; refusing stale repair')
before=list(csv.DictReader(path.open()));after=list(csv.DictReader(prepared.open()))
patches={p['item_id']:p for p in plan['patches']}
if len(before)!=len(after):raise ValueError('Row count changed')
for old,new in zip(before,after):
    if old.keys()!=new.keys():raise ValueError('Schema changed')
    for k in old:
        expected=patches[old['item_id']][k] if old['item_id'] in patches and k in ['span_text','notes'] else old[k]
        if new[k]!=expected:raise ValueError('Unrelated cell changed: '+old['item_id']+' '+k)
for name,digest in plan['protected_sha256'].items():
    if sha(Path(name))!=digest:raise ValueError('Protected input changed')
path.write_bytes(prepared.read_bytes())
manifest={'method':'source_assisted_supplemental_document_mentions','independent_personal_annotation':False,
          'agreement_scope':'Only the original common candidate pool is shared. Supplemental source-review rows are not independent paired labels.',
          'base_common_candidate_items_sha256':plan['base_common_candidate_items_sha256'],
          'source_records_sha256':plan['source_records_sha256'],'workbook_sha256':sha(path),
          'before_workbook_sha256':plan['input_sha256'],'items':plan['items'],'protected_sha256':plan['protected_sha256']}
(audit/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
p=base/'workbooks/sueda-attestation.json';x=json.loads(p.read_text())
if x['method']!='source_review' or x['independent'] is not False:raise ValueError('Personal attestation must not be rewritten')
x['workbook_sha256']['relations']=sha(path);x['source_review_updated_at']=utc_now()
x['relation_review_scope']={'common_candidates':126,'supplemental_candidates':56,
    'supplemental_manifest':'evaluation/real/sueda-review/relation-extension/manifest.json','independent_paired_labels':False}
p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
p=base/'sueda-relation-progress.json';x=json.loads(p.read_text())
x.update(status='source_review_complete_with_supplemental_items',common_candidates=126,supplemental_candidates=56,
         distinct_positive_facts=len({(r['document_id'],r['object']) for r in after if r['label']=='MENTIONS'}),source_passages_complete=True)
p.write_text(json.dumps(x,indent=2)+'\n')
print('Applied 56 exact-source passage repairs; protected candidate, second-review and participant files are unchanged.')
