"""Prepare, run, and validate evaluation against the frozen real-document corpus."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collectors.records import validate_records
from evaluation.compute_agreement import cohen_kappa
from evaluation.run_metrics import main as score_metrics
from interface.agent import AgentConfig, TrendScoutAgent


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding="utf-8")


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def load_csv(path, item_column, label_column):
    """Load a flat human label CSV and reject duplicate item IDs."""
    rows = read_csv(path)
    labels = {}
    seen = set()
    for row in rows:
        item = str(row.get(item_column, '')).strip()
        label = str(row.get(label_column, '')).strip()
        if not item:
            continue
        if item in seen:
            raise ValueError(f'duplicate item ID: {item}')
        seen.add(item)
        if label:
            labels[item] = label
    return labels


def write_csv(path, fields, rows):
    with path.open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def frozen_records(directory):
    manifest = read_json(directory / 'manifest.json')
    content = (directory / 'records.jsonl').read_bytes()
    if manifest.get('synthetic_fixture') is not False:
        raise ValueError('real source manifest required')
    if hashlib.sha256(content).hexdigest() != manifest['snapshot_sha256']:
        raise ValueError('snapshot checksum mismatch')
    for source in manifest['sources']:
        if hashlib.sha256((directory / source['file']).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('raw source checksum mismatch')
    records = [json.loads(line) for line in content.decode().splitlines() if line.strip()]
    if not 40 <= len(records) <= 50 or len({r['record_id'] for r in records}) != len(records):
        raise ValueError('40-50 unique documents required')
    if manifest['document_count'] != len(records) or validate_records(records):
        raise ValueError('invalid corpus records or count')
    if (directory / 'round-inputs.json').exists():
        inputs = read_json(directory / 'round-inputs.json')
        for name, key in [('questions.json', 'questions_sha256'), ('guidelines.json', 'guidelines_sha256'),
                          ('candidate-items.json', 'candidate_items_sha256')]:
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != inputs[key]:
                raise ValueError(f'frozen input checksum mismatch: {name}')
    return records


def prepare(directory, relation_candidates_per_document=3):
    if relation_candidates_per_document < 1:
        raise ValueError('relation candidates per document must be positive')
    records = frozen_records(directory)
    work = directory / 'workbooks'
    if work.exists() and any(work.iterdir()):
        raise ValueError('refusing to overwrite existing annotation workbooks')
    # Freeze the original question set verbatim, before any retrieval run.
    questions_bytes = (ROOT / 'evaluation/questions.seed.json').read_bytes()
    (directory / 'questions.json').write_bytes(questions_bytes)
    questions = json.loads(questions_bytes)['questions']
    guidelines = read_json(ROOT / 'evaluation/annotation_guidelines.json')
    write_json(directory / 'guidelines.json', guidelines)
    entities, relations = [], []
    # Candidates are exact offsets, with NO assigned labels. NONE is a valid
    # independent rejection. Additional mentions can be appended by both raters
    # using agreed item IDs before labelling; never align after adjudication.
    for record in records:
        text = record['text'] or ''
        matches = list(re.finditer(r'\b[A-Z][A-Za-z0-9_+.-]{2,}\b', text))[:12]
        for match in matches:
            entities.append({'item_id': f"entity:{record['record_id']}:{match.start()}:{match.end()}",
                             'document_id': record['record_id'], 'start': match.start(), 'end': match.end(),
                             'entity_text': match.group(), 'span_text': text[max(0, match.start()-100):match.end()+100],
                             'label': '', 'notes': ''})
        for match in matches[:relation_candidates_per_document]:
            relations.append({'item_id': f"relation:{record['record_id']}:{match.start()}",
                              'document_id': record['record_id'],
                              'subject': record['record_id'], 'object': match.group(),
                              'span_text': text[max(0, match.start()-100):match.end()+100],
                              'label': '', 'notes': ''})
    if len(entities) < 200 or len(relations) < 100:
        raise ValueError('not enough shared candidate spans')
    work.mkdir(exist_ok=True)
    for name, full_name in [('sueda', 'Sueda Sen'), ('mehmet', 'Mehmet Aksit')]:
        write_csv(work / f'{name}-entities.csv', list(entities[0]), entities)
        write_csv(work / f'{name}-relations.csv', list(relations[0]), relations)
        write_json(work / f'{name}-attestation.json', {
            'annotator': full_name, 'status': 'not_started', 'method': 'human',
            'independent': False, 'completed_at': None,
            'snapshot_sha256': read_json(directory / 'manifest.json')['snapshot_sha256'],
            'workbook_sha256': {}})
    write_json(directory / 'candidate-items.json', {'entities': entities, 'relations': relations})
    reviews = [{'document_id': r['record_id'], 'source_url': r['source_url'], 'title': r['title'],
                'sueda_include': '', 'mehmet_include': '', 'final_include': '', 'adjudicator': '', 'notes': ''}
               for r in records]
    write_csv(work / 'corpus-review.csv', list(reviews[0]), reviews)
    qrels = [{'question_id': q['question_id'], 'question': q['question'], 'record_id': r['record_id'],
              'source_url': r['source_url'], 'sueda_grade': '', 'mehmet_grade': '',
              'final_grade': '', 'adjudicator': '', 'notes': ''} for q in questions for r in records]
    write_csv(work / 'qrels.csv', list(qrels[0]), qrels)
    write_json(directory / 'trust-pilot.json', {
        'status': 'records_required', 'participants': [], 'task_results': [],
        'protocol': {'participants': '5-8 consenting people; pseudonymous IDs only',
                     'tasks_each': 6, 'conditions': ['citations_only', 'citations_plus_state_and_path'],
                     'design': 'Within-participant, 3 tasks per condition; counterbalance order across participants.',
                     'task_ids': [q['question_id'] for q in questions[:6]],
                     'required_result_fields': ['participant_id', 'question_id', 'condition', 'order',
                         'status_correct', 'evidence_correct', 'abstention_correct', 'duration_seconds', 'confidence'],
                     'confidence_scale': '1-5', 'correctness': 'Boolean; judge against adjudicated task key.',
                     'task_key': {}, 'consent': 'Record consent_confirmed=true per participant.'}})
    contribution = read_json(ROOT / 'evaluation/contribution-record.template.json')
    contribution['status'] = 'verification_records_required'
    contribution['user_report'] = 'User reports human work was completed; underlying annotation and pilot records not located.'
    write_json(directory / 'contribution-record.json', contribution)
    write_json(directory / 'round-inputs.json', {
        'snapshot_sha256': read_json(directory / 'manifest.json')['snapshot_sha256'],
        'questions_sha256': hashlib.sha256(questions_bytes).hexdigest(),
        'guidelines_sha256': hashlib.sha256((directory / 'guidelines.json').read_bytes()).hexdigest(),
        'candidate_items_sha256': hashlib.sha256((directory / 'candidate-items.json').read_bytes()).hexdigest()})
    print(json.dumps({'entity_candidates': len(entities), 'relation_candidates': len(relations),
                      'qrels_pairs': len(qrels), 'labels_assigned': 0}))


def annotation_agreement(directory):
    frozen_records(directory)
    guidelines = read_json(directory / 'guidelines.json')
    candidates = read_json(directory / 'candidate-items.json')
    digest = read_json(directory / 'manifest.json')['snapshot_sha256']
    reports = {}
    for kind, minimum in [('entities', 200), ('relations', 80)]:
        expected = {r['item_id']: r for r in candidates[kind]}
        labels = []
        for name in ['sueda', 'mehmet']:
            path = directory / 'workbooks' / f'{name}-{kind}.csv'
            attestation = read_json(directory / 'workbooks' / f'{name}-attestation.json')
            if (attestation.get('status') != 'complete' or attestation.get('method') != 'human'
                    or attestation.get('independent') is not True or not attestation.get('completed_at')
                    or attestation.get('snapshot_sha256') != digest
                    or attestation.get('workbook_sha256', {}).get(kind) != hashlib.sha256(path.read_bytes()).hexdigest()):
                raise ValueError(f'{name}: completed independent annotation attestation and workbook hashes required')
            rows = read_csv(path)
            ids = [r['item_id'] for r in rows]
            if len(ids) != len(set(ids)) or set(ids) != set(expected):
                raise ValueError(f'{name} {kind}: duplicated, missing, or unknown item IDs')
            allowed = set(guidelines['entity_types' if kind == 'entities' else 'relation_types']) | {'NONE'}
            for row in rows:
                if row['label'] not in allowed:
                    raise ValueError(f'{name} {kind}: missing or invalid label')
                if any(row[k] != str(v) for k, v in expected[row['item_id']].items() if k not in {'label', 'notes'}):
                    raise ValueError('candidate spans must not change between raters')
            positives = sum(r['label'] != 'NONE' for r in rows)
            if positives < minimum or (kind == 'relations' and positives > 100):
                raise ValueError(f'{name} {kind}: {positives} accepted; need {minimum}' + ('-100' if kind == 'relations' else '+'))
            labels.append({r['item_id']: r['label'] for r in rows})
        if len(expected) < 100:
            raise ValueError('100+ shared items required for each agreement analysis')
        a, b = labels
        # A single category gives an undefined kappa, even with perfect agreement.
        degenerate = len(set(a.values()) | set(b.values())) == 1
        kappa, shared = (None, len(expected)) if degenerate else cohen_kappa(a, b)
        reports[kind] = {'shared_items': shared, 'cohen_kappa': None if degenerate else kappa,
                         'undefined_reason': 'single category' if degenerate else None,
                         'disagreements': [item for item in a if a[item] != b[item]]}
    return reports


def adjudicated_qrels(directory):
    records = frozen_records(directory)
    questions = read_json(directory / 'questions.json')['questions']
    expected = {(q['question_id'], r['record_id']) for q in questions for r in records}
    rows = read_csv(directory / 'workbooks/qrels.csv')
    pairs = [(r['question_id'], r['record_id']) for r in rows]
    if len(pairs) != len(set(pairs)) or set(pairs) != expected:
        raise ValueError('qrels require every question/document pair exactly once')
    qrels = {}
    for row in rows:
        if (any(row[k] not in {'0', '1', '2'} for k in ['sueda_grade', 'mehmet_grade', 'final_grade'])
                or not row['adjudicator'].strip() or not row['notes'].strip()):
            raise ValueError('qrels require two independent grades, final grade, named adjudicator and rationale')
        qrels.setdefault(row['question_id'], {})[row['record_id']] = int(row['final_grade'])
    return {'status': 'human_adjudicated', 'illustrative': False, 'qrels': qrels,
            'snapshot_sha256': read_json(directory / 'manifest.json')['snapshot_sha256']}


def run(directory, study=None):
    records = frozen_records(directory)
    study = study or directory
    questions = read_json(study / 'questions.json')['questions']
    cohort = read_json(ROOT / 'data/registry/cohort.json')
    out = study / 'answers'
    if (study / 'unjudged-metrics.json').exists():
        raise ValueError('refusing to overwrite completed evaluation run')
    out.mkdir(exist_ok=True)
    snapshot = read_json(directory / 'manifest.json')['snapshot_sha256']
    for mode in ['bm25', 'dense', 'graph_only', 'hybrid']:
        agent = TrendScoutAgent(records, config=AgentConfig(mode=mode, encoder='hashing', demo_mode=False),
                                cohort=cohort, snapshot_id=snapshot)
        bundles = [agent.answer(q['question'], requires=q.get('needs', []), k=5,
                               question_id=q['question_id']).as_dict() for q in questions]
        (out / f'{mode}.jsonl.gz').write_bytes(gzip.compress(''.join(json.dumps(b, default=str) + '\n' for b in bundles).encode(), mtime=0))
    write_json(study / 'run-provenance.json', {
        'snapshot_sha256': snapshot,
        'questions_sha256': hashlib.sha256((study / 'questions.json').read_bytes()).hexdigest(),
        'answers': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.jsonl.gz'))},
        'encoder': 'hashing', 'provider': 'extractive',
        'dense_condition_caveat': 'Hashing is a lexical baseline, not semantic dense retrieval.'})
    score_metrics([*[str(p) for p in sorted(out.glob('*.jsonl.gz'))], '--questions', str(study / 'questions.json'),
                   '--out', str(study / 'unjudged-metrics.json')])


def source_reviewed_qrels(directory, path, study=None):
    """Validate exhaustive, source-grounded judgments without inventing raters."""
    records = {r['record_id']: r for r in frozen_records(directory)}
    study = study or directory
    payload = read_json(path)
    if (payload.get('status') != 'source_review_complete' or payload.get('illustrative') is not False
            or payload.get('human_adjudicated') is not False or not payload.get('judged_by')
            or not payload.get('rubric')):
        raise ValueError('source-review provenance and rubric required')
    if (payload.get('snapshot_sha256') != read_json(directory / 'manifest.json')['snapshot_sha256']
            or payload.get('questions_sha256') != hashlib.sha256((study / 'questions.json').read_bytes()).hexdigest()):
        raise ValueError('qrels snapshot or question checksum mismatch')
    expected = {(q['question_id'], rid) for q in read_json(study / 'questions.json')['questions'] for rid in records}
    judgments = payload.get('judgments', [])
    pairs = [(r['question_id'], r['record_id']) for r in judgments]
    if len(pairs) != len(set(pairs)) or set(pairs) != expected:
        raise ValueError('source review must judge every question/document pair exactly once')
    derived = {}
    for judgment in judgments:
        grade = judgment.get('grade')
        if type(grade) is not int or grade not in {0, 1, 2} or not judgment.get('rationale', '').strip():
            raise ValueError('valid grade and rationale required for every source judgment')
        if grade > 0 and (not judgment.get('quote') or judgment['quote'] not in records[judgment['record_id']]['text']):
            raise ValueError('positive judgments require an exact source quote')
        derived.setdefault(judgment['question_id'], {})[judgment['record_id']] = grade
    if payload.get('qrels') != derived:
        raise ValueError('qrels grades disagree with judgment records')
    return payload


def validate(directory):
    frozen_records(directory)
    errors = []
    try:
        reviews = read_csv(directory / 'workbooks/corpus-review.csv')
        ids = [r['document_id'] for r in reviews]
        if len(ids) != len(set(ids)) or set(ids) != {r['record_id'] for r in frozen_records(directory)}:
            raise ValueError('corpus review must cover every document exactly once')
        if any(r[k] not in {'yes', 'no'} for r in reviews for k in ['sueda_include', 'mehmet_include', 'final_include']):
            raise ValueError('corpus inclusion reviews missing')
        if any(not r['adjudicator'].strip() for r in reviews):
            raise ValueError('corpus review adjudicator missing')
        if not all(r['final_include'] == 'yes' for r in reviews):
            raise ValueError('excluded documents require a new frozen round; never silently change scored corpus')
    except ValueError as exc:
        errors.append(str(exc))
    qrels_operation = (lambda d: source_reviewed_qrels(d, d / 'source-reviewed-qrels.json')) if (
        directory / 'source-reviewed-qrels.json').exists() else adjudicated_qrels
    for name, operation in [('annotations', annotation_agreement), ('qrels', qrels_operation)]:
        try:
            operation(directory)
        except ValueError as exc:
            errors.append(f'{name}: {exc}')
    pilot = read_json(directory / 'trust-pilot.json')
    participants, results = pilot.get('participants', []), pilot.get('task_results', [])
    ids = [p.get('participant_id') for p in participants]
    if (not 5 <= len(ids) <= 8 or len(ids) != len(set(ids)) or not all(ids)
            or not all(p.get('consent_confirmed') is True for p in participants)):
        errors.append('pilot requires 5-8 distinct consenting participants')
    task_ids = set(pilot['protocol']['task_ids'])
    if pilot.get('status') != 'complete' or set(pilot['protocol'].get('task_key', {})) != task_ids:
        errors.append('pilot completion and adjudicated task key required')
    try:
        from evaluation.finalize_pilot import verify as verify_final_pilot
        verify_final_pilot(directory)
    except (ValueError,FileNotFoundError):
        errors.append('verified pilot adjudication and final observed-field grading required')
    for participant in ids:
        tasks = [r for r in results if r.get('participant_id') == participant]
        if (len(tasks) != 6 or {r.get('question_id') for r in tasks} != task_ids
                or {r.get('order') for r in tasks} != set(range(1, 7))
                or any(sum(r.get('condition') == c for r in tasks) != 3
                       for c in pilot['protocol']['conditions'])):
            errors.append(f'pilot participant {participant}: six unique counterbalanced tasks required')
    if any(r.get('participant_id') not in ids or type(r.get('status_correct')) is not bool
           or any(r.get(k) is not None and type(r.get(k)) is not bool for k in ['evidence_correct','abstention_correct'])
           or not isinstance(r.get('duration_seconds'), (int, float)) or r['duration_seconds'] <= 0
           or r.get('confidence') not in [1, 2, 3, 4, 5] for r in results):
        errors.append('invalid pilot measurements')
    unmeasured=sum(r.get(k) is None for r in results for k in ['evidence_correct','abstention_correct'])
    if unmeasured:
        errors.append(f'pilot has {unmeasured} unmeasured explanation-dependent assessments; full protocol completeness is not established')
    contribution = read_json(directory / 'contribution-record.json')
    if (contribution.get('status') != 'verified' or len(contribution.get('members', [])) != 4
            or any(not m.get('human_tasks') or not m.get('verification') for m in contribution['members'])):
        errors.append('four-member contribution verification records required')
    if not (directory / 'scored-metrics.json').exists():
        errors.append('scored retrieval evaluation not yet available')
    return errors


def score(directory, qrels_path=None, study=None):
    # Preserve the provenance of either supplied source reviews or adjudication.
    frozen_records(directory)
    study = study or directory
    provenance = read_json(study / 'run-provenance.json')
    snapshot = read_json(directory / 'manifest.json')['snapshot_sha256']
    if (provenance['snapshot_sha256'] != snapshot or provenance['questions_sha256'] !=
            hashlib.sha256((study / 'questions.json').read_bytes()).hexdigest()):
        raise ValueError('answer run inputs do not match this round')
    expected_questions = {q['question_id'] for q in read_json(study / 'questions.json')['questions']}
    if set(provenance['answers']) != {'bm25.jsonl.gz', 'dense.jsonl.gz', 'graph_only.jsonl.gz', 'hybrid.jsonl.gz'}:
        raise ValueError('all four retrieval conditions required')
    for name, digest in provenance['answers'].items():
        path = study / 'answers' / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('answer checksum mismatch')
        bundles = [json.loads(line) for line in gzip.decompress(path.read_bytes()).decode().splitlines() if line.strip()]
        if len(bundles) != len(expected_questions) or {b['question_id'] for b in bundles} != expected_questions:
            raise ValueError('every condition must answer every frozen question exactly once')
    if qrels_path:
        qrels = source_reviewed_qrels(directory, qrels_path, study)
    else:
        qrels = adjudicated_qrels(directory)
        qrels_path = directory / 'adjudicated-qrels.json'
        write_json(qrels_path, qrels)
    score_metrics([*[str(p) for p in sorted((study / 'answers').glob('*.jsonl.gz'))],
                   '--questions', str(study / 'questions.json'), '--qrels', str(qrels_path),
                   '--out', str(study / 'scored-metrics.json')])
    result = read_json(study / 'scored-metrics.json')
    result['judgment_provenance'] = {k: qrels.get(k) for k in ['status', 'judged_by', 'human_adjudicated', 'rubric']}
    result['ranking_unit'] = 'Unique record IDs in citation order; not raw retriever candidates.'
    result['source_qrels_sha256'] = hashlib.sha256(qrels_path.read_bytes()).hexdigest()
    write_json(study / 'scored-metrics.json', result)


def rank(directory, qrels_path, study=None):
    """Measure actual top-k document rankings independently of answer citations."""
    from evaluation.metrics import precision_at_k, recall_at_k, reciprocal_rank, ndcg_at_k
    from retrieval.hybrid import HybridRetriever, RetrievalConfig
    from retrieval.dense import build_encoder
    study = study or directory
    if not qrels_path:
        raise ValueError('rank requires --qrels')
    judgments = source_reviewed_qrels(directory, qrels_path, study)
    records = frozen_records(directory)
    questions = read_json(study / 'questions.json')['questions']
    conditions = []
    for mode in ['bm25', 'dense', 'hybrid']:
        retriever = HybridRetriever.from_records(records, config=RetrievalConfig(mode=mode),
                                                  encoder=build_encoder('hashing'))
        rows = []
        for question in questions:
            hits = retriever.search(question['question'], k=5)
            ids = [h['record_id'] for h in hits]
            relevant = judgments['qrels'][question['question_id']]
            rows.append({'question_id': question['question_id'],
                         'ranking': [{'rank': n, 'record_id': h['record_id'], 'score': h['score']}
                                     for n, h in enumerate(hits, 1)],
                         'positive_documents': sum(g > 0 for g in relevant.values()),
                         'precision_at_5': precision_at_k(ids, relevant, 5),
                         'recall_at_5': recall_at_k(ids, relevant, 5),
                         'reciprocal_rank_at_5': reciprocal_rank(ids, relevant),
                         'ndcg_at_5': ndcg_at_k(ids, relevant, 5)})
        def mean(key):
            values = [r[key] for r in rows if r[key] is not None]
            return round(statistics.mean(values), 6) if values else None
        conditions.append({'condition': mode, 'questions': len(rows),
                           'questions_with_positive_documents': sum(r['positive_documents'] > 0 for r in rows),
                           'precision_at_5': mean('precision_at_5'), 'recall_at_5': mean('recall_at_5'),
                           'mrr_at_5': mean('reciprocal_rank_at_5'), 'ndcg_at_5': mean('ndcg_at_5'),
                           'per_question': rows})
    report = {'status': 'scored', 'ranking_unit': 'Raw retriever top-5, distinct documentary origins',
              'snapshot_sha256': judgments['snapshot_sha256'], 'questions_sha256': judgments['questions_sha256'],
              'qrels_sha256': hashlib.sha256(qrels_path.read_bytes()).hexdigest(),
              'judged_by': judgments['judged_by'], 'human_adjudicated': judgments['human_adjudicated'],
              'encoder': 'hashing', 'conditions': conditions,
              'limitations': ['The dense condition is a hashing lexical baseline, not semantic embeddings.',
                             'Raw retrieval over all frozen documents; no answer-stage filtering or generation.',
                             'Graph-only produces structured query results and is evaluated separately in answer bundles.',
                             'Recall/nDCG are undefined on zero-positive questions; report their count.']}
    write_json(study / 'retrieval-metrics.json', report)
    print(json.dumps({'out': str(study / 'retrieval-metrics.json'),
                      'conditions': [{k: v for k, v in c.items() if k != 'per_question'} for c in conditions]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'agreement', 'score', 'rank', 'validate'])
    parser.add_argument('--directory', type=Path, default=ROOT / 'evaluation/real')
    parser.add_argument('--study-directory', type=Path, help='Separate frozen question set and answer outputs.')
    parser.add_argument('--qrels', type=Path, help='Exhaustive source-review judgments with provenance.')
    parser.add_argument('--relation-candidates-per-document', type=int, default=3,
                        help='Candidate relation spans per document when preparing a new round.')
    args = parser.parse_args()
    try:
        if args.action == 'agreement':
            result = annotation_agreement(args.directory)
            write_json(args.directory / 'agreement.json', result)
            print(json.dumps(result, indent=2))
        elif args.action == 'validate':
            errors = validate(args.directory)
            print(json.dumps({'status': 'incomplete' if errors else 'complete', 'errors': errors}, indent=2))
            return int(bool(errors))
        elif args.action == 'run':
            run(args.directory, args.study_directory)
        elif args.action == 'score':
            score(args.directory, args.qrels, args.study_directory)
        elif args.action == 'rank':
            rank(args.directory, args.qrels, args.study_directory)
        else:
            prepare(args.directory, args.relation_candidates_per_document)
    except (ValueError, KeyError, OSError) as exc:
        print(f'Cannot {args.action}: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
