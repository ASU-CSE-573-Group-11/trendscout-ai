"""Package Sueda's first source review as one consistent candidate revision.

The shared candidates are frozen before a second review. This packet does not
change the earlier release corpus or attest independent personal annotation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from evaluation.real_round import ROOT, frozen_records, read_json


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    with path.open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def unique(rows, key, description):
    values = [key(row) for row in rows]
    if len(values) != len(set(values)):
        raise ValueError(f'duplicate {description}')
    return set(values)


def write_rows(path, rows):
    with path.open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def build(directory):
    records = frozen_records(directory)
    audit = directory / 'sueda-review'
    out = audit / 'candidate-review-v2'
    if out.exists():
        raise ValueError('refusing to overwrite frozen annotation packet')
    entities = read_rows(directory / 'workbooks/sueda-entities.csv') + read_rows(audit / 'additional-entities.csv')
    sample = read_rows(audit / 'relations-90.csv')
    negatives = [row for row in read_rows(directory / 'workbooks/sueda-relations.csv') if row['label'] == 'NONE'][:10]
    relations = sample + negatives
    unique(entities, lambda r: r['item_id'], 'entity item IDs')
    unique(relations, lambda r: r['item_id'], 'relation item IDs')
    candidates = {}
    for kind, rows in [('entities', entities), ('relations', relations)]:
        candidates[kind] = [{**row, 'label': '', 'notes': ''} for row in rows]
    out.mkdir()
    write_rows(out / 'reviewed-entities.csv', entities)
    write_rows(out / 'reviewed-relations.csv', relations)
    (out / 'candidates.json').write_text(json.dumps(candidates, indent=2) + '\n')
    manifest = {
        'revision': 2,
        'base_snapshot_sha256': read_json(directory / 'manifest.json')['snapshot_sha256'],
        'base_candidate_items_sha256': sha(directory / 'candidate-items.json'),
        'review_method': 'single_source_review',
        'prepared_for': 'Sueda Sen',
        'independent_personal_annotation_attested': False,
        'documents': len(records),
        'candidate_counts': {'entities': len(entities), 'relations': len(relations)},
        'accepted_counts': {kind: sum(r['label'] != 'NONE' for r in rows)
                            for kind, rows in [('entities', entities), ('relations', relations)]},
        'relation_sampling': '90 distinct documentary MENTIONS facts, round-robin by source document, plus the first 10 rejected original candidates. This is candidate classification, not a population sample of semantic relations.',
        'files': {name: sha(out / name) for name in ['candidates.json', 'reviewed-entities.csv', 'reviewed-relations.csv']},
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return validate(out, records, read_json(directory / 'guidelines.json'))


def validate(packet, records, guidelines):
    manifest = read_json(packet / 'manifest.json')
    for name, digest in manifest['files'].items():
        if sha(packet / name) != digest:
            raise ValueError('annotation packet checksum mismatch: ' + name)
    by_id = {r['record_id']: r for r in records}
    candidates = read_json(packet / 'candidates.json')
    counts = {}
    for kind in ['entities', 'relations']:
        rows = read_rows(packet / f'reviewed-{kind}.csv')
        ids = unique(rows, lambda r: r['item_id'], kind + ' item IDs')
        frozen = {r['item_id']: r for r in candidates[kind]}
        if len(frozen) != len(candidates[kind]) or ids != set(frozen):
            raise ValueError('annotation packet candidate IDs differ: ' + kind)
        allowed = set(guidelines['entity_types' if kind == 'entities' else 'relation_types']) | {'NONE'}
        for row in rows:
            if row['label'] not in allowed or not row['notes'].strip():
                raise ValueError('invalid or unsupported ' + kind + ' label')
            if any(value != frozen[row['item_id']][key] for key, value in row.items() if key not in {'label', 'notes'}):
                raise ValueError('annotation candidate fields changed: ' + kind)
            if frozen[row['item_id']]['label'] or frozen[row['item_id']]['notes']:
                raise ValueError('shared candidate list exposes first-review labels')
            text = by_id[row['document_id']]['text']
            if kind == 'entities':
                start, end = int(row['start']), int(row['end'])
                if not 0 <= start < end <= len(text) or text[start:end] != row['entity_text']:
                    raise ValueError('entity offsets do not match source')
                expected_id = f"entity:{row['document_id']}:{start}:{end}"
            else:
                start = int(row['item_id'].rsplit(':', 1)[-1])
                if row['subject'] != row['document_id'] or text[start:start + len(row['object'])] != row['object']:
                    raise ValueError('relation endpoint does not match source')
                expected_id = f"relation:{row['document_id']}:{start}"
            if row['item_id'] != expected_id or row['span_text'] not in text:
                raise ValueError('candidate identity or passage is invalid')
        counts[kind] = sum(r['label'] != 'NONE' for r in rows)
        if manifest['candidate_counts'][kind] != len(rows) or manifest['accepted_counts'][kind] != counts[kind]:
            raise ValueError('annotation packet counts differ')
    if counts['entities'] < 200 or not 80 <= counts['relations'] <= 100:
        raise ValueError('source review packet does not meet planned counts')
    return {'status': 'single_source_review_packet_verified', 'accepted': counts,
            'candidates': manifest['candidate_counts'], 'documents': len(records)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'evaluation/real')
    print(json.dumps(build(parser.parse_args().directory), indent=2))
