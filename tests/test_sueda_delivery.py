import csv
import json
import hashlib
import shutil

import pytest

from collectors.cohort import alias_index, match_companies
from collectors.http import FetchError
from collectors.origin import assign_origin_clusters
from collectors.records import make_record
from collectors.rss import parse_feed
from collectors.snapshot import replay
from collectors.yc import collect_yc_identity
from evaluation.real_round import ROOT, frozen_records


def test_rss_rfc_publication_date_is_preserved():
    body=(ROOT/'tests/fixtures/techcrunch.xml').read_text()
    assert parse_feed(body,'https://example.com/feed')[0]['published_at']=='2026-10-01T12:00:00Z'


def test_atom_update_is_not_invented_as_publication():
    body='<feed xmlns="http://www.w3.org/2005/Atom"><title>T</title><entry><title>T</title><updated>2026-11-20T00:00:00Z</updated><link href="https://example.com/a"/></entry></feed>'
    assert parse_feed(body,'https://example.com/feed')[0]['published_at'] is None


@pytest.mark.parametrize('body',['<html><title>Error</title></html>','not a feed',''])
def test_invalid_feed_cannot_masquerade_as_empty_success(body):
    with pytest.raises(FetchError,match='invalid RSS'):
        parse_feed(body,'https://example.com/feed')


def test_common_words_do_not_become_cohort_mentions():
    companies=[{'company_id':'continue','name':'Continue','aliases':['Continue']},
               {'company_id':'replicate','name':'Replicate','aliases':['Replicate']}]
    aliases=alias_index(companies)
    assert match_companies('Partners continue profiting as researchers replicate results.',aliases)==[]
    assert match_companies('Continue adds a coding assistant to the IDE.',aliases)==[('continue','Continue')]
    assert match_companies('Replicate launches image generation models.',aliases)==[('replicate','Replicate')]


def test_registry_identity_does_not_claim_page_verification():
    rows,_=collect_yc_identity({'frozen_at':'2026-10-30','companies':[{
        'company_id':'x','name':'X','status':'included','yc_url':'https://www.ycombinator.com/companies/x'}]})
    assert rows[0]['published_at'] is None and rows[0]['event_at'] is None
    assert rows[0]['metadata']['directory_verified'] is False
    assert rows[0]['publisher']=='TrendScout cohort registry'


def test_similar_titles_with_distinct_passages_remain_independent():
    rows=[make_record(source_type='news',source_url=f'https://example.com/{i}',
        title='LangChain evaluation announcement',text=text,publisher=str(i))
        for i,text in enumerate(['New Python evaluation tooling improves production reliability and diagnostics.',
                                'Customers report pricing changes and support delays in separate interviews.'])]
    assert len({r['origin_cluster_id'] for r in assign_origin_clusters(rows)})==2


def test_reviewed_spans_are_grounded():
    directory=ROOT/'evaluation/real'
    records={r['record_id']:r for r in frozen_records(directory)}
    review=directory/'sueda-review'
    for file in [directory/'workbooks/sueda-entities.csv',review/'additional-entities.csv']:
        for row in csv.DictReader(file.open()):
            assert row['label']
            assert records[row['document_id']]['text'][int(row['start']):int(row['end'])]==row['entity_text']
    relations=list(csv.DictReader((review/'relations-90.csv').open()))
    assert len(relations)==90 and len({(r['document_id'],r['object']) for r in relations})==90
    assert all(r['object'] in r['span_text'] for r in relations)


def test_first_review_preserves_existing_second_review_and_pilot_records(tmp_path):
    from evaluation.review_workbooks import review
    source = ROOT / 'evaluation/real'
    for name in ['manifest.json', 'records.jsonl', 'round-inputs.json', 'questions.json',
                 'candidate-items.json', 'guidelines.json', 'source-reviewed-qrels.json']:
        shutil.copy(source / name, tmp_path / name)
    shutil.copytree(source / 'sources', tmp_path / 'sources')
    work = tmp_path / 'workbooks'
    work.mkdir()
    for name in ['sueda-entities.csv', 'sueda-relations.csv', 'corpus-review.csv', 'qrels.csv', 'sueda-attestation.json']:
        shutil.copy(source / 'sueda-review' / ('before-' + name), work / name)
    from evaluation.real_round import read_csv
    for name in ['corpus-review.csv', 'qrels.csv']:
        items = read_csv(work / name)
        items[0]['notes'] = 'Existing second-review note.'
        with (work / name).open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(items[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(items)
    protected = [work / 'mehmet-entities.csv', work / 'mehmet-relations.csv', tmp_path / 'trust-pilot.json']
    # Test-only sentinels demonstrate preservation even after real inputs arrive.
    for path in protected[:2]:
        path.write_text('item_id,label\nexisting,Technology\n')
    protected[-1].write_text(json.dumps({'participants': [{'participant_id': 'test-only'}], 'task_results': []}))
    before = {p: p.read_bytes() for p in protected}
    review(tmp_path)
    assert all(p.read_bytes() == before[p] for p in protected)
    for name in ['corpus-review.csv', 'qrels.csv']:
        assert read_csv(work / name)[0]['notes'].startswith('Existing second-review note.\n')


def test_delivery_verification_includes_frozen_annotation_packet_and_answer_provenance():
    from evaluation.verify_sueda_delivery import verify
    report = verify()
    assert report['annotation_packet']['accepted'] == {'entities': 500, 'relations': 90}
    assert report['annotation_packet']['candidates'] == {'entities': 776, 'relations': 100}
    assert report['verified_saved_answers'] == 224


def test_duplicate_rows_cannot_hide_missing_corpus_or_qrels_items():
    from evaluation.verify_sueda_delivery import exact_keys
    with pytest.raises(ValueError, match='duplicate qrels'):
        exact_keys([{'q': 'a'}, {'q': 'a'}], lambda r: r['q'], {'a', 'b'}, 'qrels pairs')
    with pytest.raises(ValueError, match='missing or unknown'):
        exact_keys([{'id': 'a'}], lambda r: r['id'], {'a', 'b'}, 'corpus document IDs')


@pytest.mark.parametrize('filename', ['candidates.json', 'reviewed-entities.csv', 'reviewed-relations.csv'])
def test_annotation_packet_detects_edited_files(tmp_path, filename):
    from evaluation.annotation_packet import validate
    source = ROOT / 'evaluation/real'
    shutil.copytree(source / 'sueda-review/candidate-review-v2', tmp_path / 'packet')
    with (tmp_path / 'packet' / filename).open('a') as handle:
        handle.write('\n')
    with pytest.raises(ValueError, match='checksum mismatch'):
        validate(tmp_path / 'packet', frozen_records(source), json.loads((source / 'guidelines.json').read_text()))


def test_annotation_packet_blinds_candidate_labels(tmp_path):
    from evaluation.annotation_packet import validate
    source = ROOT / 'evaluation/real'
    packet = tmp_path / 'packet'
    shutil.copytree(source / 'sueda-review/candidate-review-v2', packet)
    candidates = json.loads((packet / 'candidates.json').read_text())
    candidates['entities'][0]['label'] = 'Technology'
    (packet / 'candidates.json').write_text(json.dumps(candidates))
    manifest = json.loads((packet / 'manifest.json').read_text())
    manifest['files']['candidates.json'] = hashlib.sha256((packet / 'candidates.json').read_bytes()).hexdigest()
    (packet / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='exposes first-review labels'):
        validate(packet, frozen_records(source), json.loads((source / 'guidelines.json').read_text()))


@pytest.mark.parametrize('problem', ['qrels_digest', 'metric_value'])
def test_scored_study_verifier_rejects_stale_or_wrong_metrics(tmp_path, problem):
    from evaluation.verify_sueda_delivery import verify_study
    source = ROOT / 'evaluation/real'
    for name in ['source-reviewed-qrels.json', 'questions.json', 'run-provenance.json',
                 'scored-metrics.json', 'retrieval-metrics.json']:
        shutil.copy(source / name, tmp_path / name)
    (tmp_path / 'answers').symlink_to(source / 'answers', target_is_directory=True)
    report = json.loads((tmp_path / 'scored-metrics.json').read_text())
    if problem == 'qrels_digest':
        report['source_qrels_sha256'] = 'outdated'
    else:
        report['conditions'][0]['questions'] += 1
    (tmp_path / 'scored-metrics.json').write_text(json.dumps(report))
    with pytest.raises(ValueError, match='checksum mismatch' if problem == 'qrels_digest' else 'metrics differ'):
        verify_study(source, tmp_path)
