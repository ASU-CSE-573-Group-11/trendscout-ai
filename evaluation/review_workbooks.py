"""Apply a documented single source review to Sueda's existing worksheets.

This records source decisions, not a statement that two people independently
annotated the material. Existing second-review and participant records are preserved.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from evaluation.real_round import ROOT, frozen_records, read_json, write_json
from collectors.records import utc_now

# Reviewed candidate vocabulary: named software, APIs, encodings, models and
# algorithms are Technology; named products are Product. Headings, imperatives,
# personal handles and underspecified fragments have no supported entity type.
TECHNOLOGIES = set('''API ASCII AgentWorkflow AnthropicCompletionResponse
BaseIndex.delete_ref_doc CLI CTE ChatDeepSeek ChatGroq ChatMemoryBuffer
ChatMistralAI ChatXAI CodeSplitter ContextOverflowError DeprecationWarning
DocumentBlock DocumentSummaryIndex.delete_nodes EmbeddingStartEvent
FunctionCallingProgram FunctionTool GPT-6 GPT-6.2 HITL HTMLNodeParser HTTP
HotpotQA IPEX IngestionPipeline JSON Java KeyError LLM LLMGuardrailCompletedEvent
LLMReranker Langchain1.x LiteLLM LiteLLM-compatible LlamaDebugHandler M2.7 MMR
MediaResource.hash MetadataFilters MockFunctionCallingLLM ModelRefusalError
ModelRequest OpenAI-compatible OpenAIClassifier OpenCLIP PNG Pillow PyMuPDF
Pydantic PydanticOutputParser Python QueryFusionRetriever._aretrieve RagTool
RayIngestionPipeline SQLDatabase.run_sql SemanticDoubleMergingSplitterNodeParser
SlidingWindowRateLimiter SparseEmbeddingStartEvent StructuredLLMRerank TextNode
TokenBudgetHandler TypeError UTF-8 ValidationError ValueError
VectorStoreQueryOutputParser VideoBlock XPU ZeroDivisionError'''.split())
PRODUCTS = set('''AgentMesh Airweave ApertureDB Astra Azure Bedrock ChromaDB Claude
Fable LangSmith MiniMax Mintlify Mistral Mythos Opus Qdrant Sol'''.split())
STARTUPS = {'CrewAI', 'LlamaIndex', 'Groq', 'OpenAI'}


def entity_label(value):
    if value in TECHNOLOGIES:
        return 'Technology'
    if value in PRODUCTS:
        return 'Product'
    if value in STARTUPS:
        return 'Startup'
    return 'NONE'


def prepare_csv(path, transform):
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        transform(row)
    return fields, rows


def append_note(row, note):
    existing = row.get('notes', '')
    row['notes'] = existing + '\n' + note if existing.strip() else note


def write_supplement(audit, records, entities):
    """Add exact named spans omitted by the capitalized-first-12 seed.

    Keep these outside the frozen shared candidate list: a later paired round
    must agree on additional IDs before any second-review labels are aligned.
    """
    existing={(r['document_id'],int(r['start']),int(r['end'])) for r in entities}
    vocabulary=TECHNOLOGIES | PRODUCTS | STARTUPS
    pattern=re.compile(r'(?<!\w)('+'|'.join(re.escape(t) for t in sorted(vocabulary,key=len,reverse=True))+r')(?!\w)')
    additional=[]
    relation_facts={}
    for record in records.values():
        for match in pattern.finditer(record['text']):
            span=record['text'][max(0,match.start()-100):match.end()+100]
            key=(record['record_id'],match.start(),match.end())
            if key not in existing:
                additional.append({'item_id':f"entity:{record['record_id']}:{match.start()}:{match.end()}",
                    'document_id':record['record_id'],'start':match.start(),'end':match.end(),
                    'entity_text':match.group(),'span_text':span,'label':entity_label(match.group()),
                    'notes':'Supplementary exact named span omitted by the frozen first-12 candidate seed.'})
            # Sample distinct document/object facts, not duplicate mention edges.
            relation_facts.setdefault((record['record_id'],match.group()),{
                'item_id':f"relation:{record['record_id']}:{match.start()}",
                'document_id':record['record_id'],'subject':record['record_id'],
                'object':match.group(),'span_text':span,'label':'MENTIONS',
                'notes':'Distinct document/named-object fact. Supporting text is quoted; no causal relation inferred.'})
    # A deterministic 90-fact documentary relation sample. All qualifying facts
    # are retained in the inventory so the sample size cannot hide exclusions.
    relations=list(relation_facts.values())
    by_document={record_id:[] for record_id in records}
    for relation in relations:
        by_document[relation['document_id']].append(relation)
    sample=[]
    for offset in range(max(map(len,by_document.values()),default=0)):
        for group in by_document.values():
            if offset<len(group) and len(sample)<90:
                sample.append(group[offset])
    for name,rows in [('additional-entities.csv',additional),('relation-inventory.csv',relations),
                      ('relations-90.csv',sample)]:
        if not rows:
            raise ValueError('no supported supplementary spans')
        with (audit/name).open('w',newline='',encoding='utf-8') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]), lineterminator="\n");writer.writeheader();writer.writerows(rows)
    return {'additional_entity_mentions':len(additional),'distinct_document_object_relations':len(relations),
            'documentary_relation_sample':min(90,len(relations)),
            'supplement_scope':'Single source-review appendix; not silently added to frozen pairwise candidates.'}


def review(directory):
    records = {r['record_id']:r for r in frozen_records(directory)}
    work = directory/'workbooks'
    audit = directory/'sueda-review'
    if audit.exists():
        raise ValueError('review already exists; preserve existing decisions')
    if any(row.get('label','').strip() for kind in ['entities','relations']
           for row in csv.DictReader((work/f'sueda-{kind}.csv').open())):
        raise ValueError('refusing to overwrite existing labels')
    qrels = read_json(directory/'source-reviewed-qrels.json')
    judgments = {(r['question_id'],r['record_id']):r for r in qrels['judgments']}
    prepared = {}

    def label_entity(row):
        text = records[row['document_id']]['text']
        if text[int(row['start']):int(row['end'])] != row['entity_text']:
            raise ValueError('entity offsets do not match frozen source')
        row['label'] = entity_label(row['entity_text'])
        append_note(row, 'Named software/model/API/algorithm explicitly present at frozen source offsets.'
                    if row['label']!='NONE' else
                    'Reject: heading, imperative, ordinary word, personal handle, or underspecified fragment.')
    prepared['sueda-entities.csv'] = prepare_csv(work/'sueda-entities.csv',label_entity)
    entities = prepared['sueda-entities.csv'][1]

    def label_relation(row):
        if row['object'] not in row['span_text']:
            raise ValueError('relation object absent from candidate passage')
        row['label'] = 'MENTIONS' if entity_label(row['object'])!='NONE' else 'NONE'
        append_note(row, 'Document explicitly mentions the named object. No causal, hiring or funding relation inferred.'
                    if row['label']=='MENTIONS' else 'Reject relation: candidate object is not an accepted named entity.')
    prepared['sueda-relations.csv'] = prepare_csv(work/'sueda-relations.csv',label_relation)
    relations = prepared['sueda-relations.csv'][1]

    def include(row):
        if row['document_id'] not in records:
            raise ValueError('unknown corpus document')
        row['sueda_include']='yes'
        append_note(row, 'Retain in the release-document study. Release notes do not establish hiring/funding growth. Single source review.')
    prepared['corpus-review.csv'] = prepare_csv(work/'corpus-review.csv',include)
    corpus = prepared['corpus-review.csv'][1]

    def grade(row):
        judgment=judgments[(row['question_id'],row['record_id'])]
        row['sueda_grade']=str(judgment['grade'])
        append_note(row, 'First source review: '+judgment['rationale'])
    prepared['qrels.csv'] = prepare_csv(work/'qrels.csv',grade)
    grades = prepared['qrels.csv'][1]
    # Validate all transforms before changing a worksheet. Preserve original
    # notes from other reviewers and exact pre-review files for recovery.
    audit.mkdir()
    for name in [*prepared, 'sueda-attestation.json']:
        (audit/('before-'+name)).write_bytes((work/name).read_bytes())
    supplement = write_supplement(audit, records, entities)
    for name, (fields, values) in prepared.items():
        staged = audit / ('prepared-' + name)
        with staged.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
            writer.writeheader()
            writer.writerows(values)
    for name in prepared:
        (audit / ('prepared-' + name)).replace(work / name)
    digest=read_json(directory/'manifest.json')['snapshot_sha256']
    write_json(work/'sueda-attestation.json',{
        'annotator':'Sueda Sen', 'prepared_for':'Sueda Sen', 'reviewer':'Project source review',
        'status':'source_review_complete', 'method':'source_review', 'independent':False,
        'completed_at':utc_now(), 'snapshot_sha256':digest,
        'workbook_sha256':{kind:hashlib.sha256((work/f'sueda-{kind}.csv').read_bytes()).hexdigest()
                           for kind in ['entities','relations']},
        'scope':'Prepared on behalf of the assigned owner. No assertion of personal independent annotation.'})
    report={'snapshot_sha256':digest,'review_method':'single_source_review',
        'entity_candidates_reviewed':len(entities),'accepted_entity_candidates':sum(r['label']!='NONE' for r in entities),
        'relation_candidates_reviewed':len(relations),'accepted_relation_candidates':sum(r['label']!='NONE' for r in relations),
        'corpus_first_decisions':len(corpus),'qrels_first_grades':len(grades),
        'second_review':'preserved; not supplied by this review','cohen_kappa':None,
        'pilot':'Participant records required.',
        'limitation':'Candidate seed includes many headings. Counts reflect supported labels, not target-driven substitutions.'}
    report.update(supplement)
    report['total_source_reviewed_entity_mentions']=report['accepted_entity_candidates']+report['additional_entity_mentions']
    write_json(audit/'summary.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'evaluation/real')
    review(parser.parse_args().directory)
