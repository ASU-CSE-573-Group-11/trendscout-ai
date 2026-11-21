"""Verify source-only supplemental relation rows without changing the shared pool."""
import hashlib
import json


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(directory,candidates,records,workbook_rows):
    common={r['item_id']:r for r in candidates['relations']}
    manifest_path=directory/'sueda-review/relation-extension/manifest.json'
    extra={}
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if manifest['base_common_candidate_items_sha256']!=sha(directory/'candidate-items.json') or manifest['source_records_sha256']!=sha(directory/'records.jsonl'):
            raise ValueError('Supplemental relation source binding changed')
        if manifest['workbook_sha256']!=sha(directory/'workbooks/sueda-relations.csv'):
            raise ValueError('Supplemental relation workbook checksum mismatch')
        if manifest['independent_personal_annotation'] is not False:
            raise ValueError('Source-only supplement cannot assert independent personal annotation')
        extra={r['item_id']:r for r in manifest['items']}
        if len(extra)!=len(manifest['items']) or set(extra)&set(common):raise ValueError('Supplemental relation item identity collision')
        for item in extra.values():
            text=records[item['document_id']]['text']
            if item['subject']!=item['document_id'] or item['label']!='MENTIONS' or item['object'] not in item['span_text'] or text[item['start']:item['end']]!=item['span_text']:
                raise ValueError('Unsupported supplemental relation passage')
    actual=[r['item_id'] for r in workbook_rows]
    if len(actual)!=len(set(actual)) or set(actual)!=set(common)|set(extra):
        raise ValueError('Missing or unknown source relation item IDs')
    for row in workbook_rows:
        expected=common.get(row['item_id'],extra.get(row['item_id']))
        if any(row[k]!=expected[k] for k in ['document_id','subject','object','span_text']):
            raise ValueError('Source relation fields differ from registered candidate or supplement')
        if row['item_id'] in extra and row['label']!=extra[row['item_id']]['label']:
            raise ValueError('Supplemental source label differs from registered decision')
        if row['label'] not in {'NONE','MENTIONS'} or not row['notes'].strip():
            raise ValueError('Invalid documentary source relation label or notes')
        if row['label']=='MENTIONS':
            text=records[row['document_id']]['text']
            if row['subject']!=row['document_id'] or row['object'] not in row['span_text'] or row['span_text'] not in text:
                raise ValueError('Unsupported documentary mention passage')
    positive=[r for r in workbook_rows if r['label']=='MENTIONS']
    return {'shared_candidate_items':len(common),'supplemental_source_items':len(extra),
            'positive_mention_occurrences':len(positive),'distinct_document_object_facts':len({(r['document_id'],r['object']) for r in positive}),
            'supplement_is_independent_paired_annotation':False}
