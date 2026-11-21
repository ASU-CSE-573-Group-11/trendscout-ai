"""Export grounded extraction records and run mixed-corpus integration/ablations.

Extraction outputs and component relevance are diagnostics, not independent
annotation agreement or temporal answer correctness.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

from evaluation.real_round import (ROOT, read_json, write_json, write_csv, frozen_records,
                                   annotation_agreement, rank, score)
from graph.evidence import make_evidence_entry, evidence_to_graph
from graph.import_contract import records_to_graph
from graph.rdf import serialize_rdf
from graph.shacl import validate_records as validate_shacl
from interface.agent import AgentConfig, TrendScoutAgent
from evaluation.run_metrics import main as score_metrics

LEXICON = {
    'LangChain':'Startup', 'LlamaIndex':'Startup', 'Browserbase':'Startup',
    'CrewAI':'Startup', 'Langfuse':'Startup', 'CapitalG':'Investor',
    'Norwest':'Investor', 'Greylock':'Investor', 'Notable Capital':'Investor',
    'LangSmith':'Product', 'LangGraph':'Product', 'LlamaParse':'Product',
    'LlamaCloud':'Product', 'Python':'Technology', 'TypeScript':'Technology',
    'Kubernetes':'Technology', 'Docker':'Technology', 'LLM':'Technology',
    'LLMs':'Technology', 'AI':'Technology', 'RAG':'Technology',
    'retrieval':'Skill', 'evaluation':'Skill', 'MLOps':'Skill', 'NLP':'Skill',
}

# Each rule describes an explicit component of a question. No source record
# alone is labelled as proving a cross-time increase or a causal relationship.
COMPONENTS = {
 'q-pilot-github-mlops': ({'github','job'}, None, r'\bmlops\b'),
 'q-investors-later-hiring': ({'funding','job'}, None, r'\b(retrieval|evaluation)\b'),
 'q-sector-attention': ({'public_voice'}, None, None),
 'q-langchain-github-since-september': ({'github','job'}, 'langchain', None),
 'q-crewai-activity-eight-weeks': ({'github'}, 'crewai', None),
 'q-startups-multi-signal-ten-weeks': ({'github','job'}, None, None),
 'q-funding-after-hiring': ({'funding','job'}, None, r'\b(retrieval|evaluation)\b'),
 'q-sector-multi-origin': ({'public_voice','news'}, None, None),
 'q-company-slowed-commits': ({'github'}, None, None),
 'q-llamaindex-retrieval-postings': ({'job'}, 'llamaindex', r'\bretrieval\b'),
 'q-e2b-sandbox-coverage': ({'news','public_voice'}, 'e2b', None),
 'q-browserbase-agent-activity': ({'github','public_voice'}, 'browserbase', None),
 'q-composio-tool-postings': ({'job'}, 'composio', None),
 'q-letta-memory-coverage': ({'news','github'}, 'letta', None),
 'q-langfuse-observability-signals': ({'github','job'}, 'langfuse', None),
 'q-haystack-rag-hiring': ({'job'}, 'deepset', r'\b(rag|nlp)\b'),
 'q-funding-before-github-growth': ({'funding','github'}, None, None),
}


def extract(records):
    entities, relations = [], []
    pattern = re.compile(r'(?<!\w)('+'|'.join(re.escape(k) for k in sorted(LEXICON,key=len,reverse=True))+r')(?!\w)')
    for record in records:
        for match in pattern.finditer(record['text']):
            entity = {'item_id':f"mention:{record['record_id']}:{match.start()}:{match.end()}",
                'document_id':record['record_id'], 'start':match.start(), 'end':match.end(),
                'entity_text':match.group(), 'label':LEXICON[match.group()],
                'span_text':record['text'][max(0,match.start()-80):match.end()+80],
                'source_url':record['source_url'], 'method':'exact_lexicon_v1',
                'review_status':'pending'}
            entities.append(entity)
            relations.append({'item_id':'relation:'+entity['item_id'],
                'document_id':record['record_id'], 'subject':record['record_id'],
                'object':entity['entity_text'], 'label':'MENTIONS',
                'start':match.start(), 'end':match.end(), 'span_text':entity['span_text'],
                'method':'exact_document_mention_v1', 'review_status':'pending'})
    return entities, relations


def component_judgment(question, record):
    rule = COMPONENTS.get(question['question_id'])
    if not rule:
        return 0, '', 'No documentary component rule: policy/negative-control questions remain unjudged as positive.'
    kinds, company, job_pattern = rule
    if record['source_type'] not in kinds or (company and record['company_id']!=company):
        return 0, '', 'Source kind or company does not match the required component.'
    text = record['text']
    if record['source_type']=='job' and job_pattern and not re.search(job_pattern,text,re.I):
        return 0, '', 'Job passage does not explicitly mention the requested skill.'
    excerpt_pattern = (job_pattern or r'\b(role|responsibilities|hiring|engineer\w*|looking for)\b') if record['source_type']=='job' else (
        r'\b(raised|raises|funding|financing)\b' if record['source_type']=='funding' else None)
    match = re.search(excerpt_pattern,text,re.I) if excerpt_pattern else None
    start = max(0,match.start()-100) if match else 0
    quote = text[start:start+300]
    return 1, quote, ('Explicit '+record['source_type']+' evidence component only; this record does not alone '
                      'establish growth, first hiring, independent corroboration, or a cross-time path.')


def integrate(directory):
    out = directory/'integration'
    if out.exists():
        raise ValueError('refusing to overwrite existing integration outputs')
    records = frozen_records(directory)
    manifest = read_json(directory/'manifest.json')
    questions = read_json(directory/'questions.json')['questions']
    out.mkdir()
    entities, relations = extract(records)
    write_csv(out/'entities.csv', list(entities[0]), entities)
    write_csv(out/'relations.csv', list(relations[0]), relations)
    write_json(out/'extraction-summary.json', {'status':'extraction_complete_review_pending',
        'entity_mentions':len(entities), 'document_mention_relations':len(relations),
        'method':'Exact case-sensitive lexicon matches with offsets; MENTIONS only.',
        'independent_annotation_agreement':None,
        'limitation':'Extraction predictions are not gold labels or two independent annotation sets.'})
    reviews = [{'document_id':r['record_id'], 'source_url':r['source_url'],
                'include':'yes', 'review_basis':'Public cohort funding/job/dated commit evidence; retained raw source.',
                'scope_limit': 'Current jobs do not establish hiring growth.' if r['source_type']=='job'
                    else 'Weekly records share a repository origin.' if r['source_type']=='github'
                    else 'First-party funding announcement; event date may be unknown.'} for r in records]
    write_csv(out/'source-inclusion-review.csv', list(reviews[0]), reviews)

    qrels, judgments, coverage = {}, [], []
    for question in questions:
        qid = question['question_id']
        qrels[qid] = {}
        for record in records:
            grade, quote, rationale = component_judgment(question,record)
            qrels[qid][record['record_id']] = grade
            judgments.append({'question_id':qid,'record_id':record['record_id'],'grade':grade,
                              'quote':quote,'rationale':rationale,'source_url':record['source_url']})
        coverage.append({'question_id':qid,'positive_component_records':sum(qrels[qid].values()),
                         'answer_correctness_established':False})
    qrels_path = out/'component-qrels.json'
    write_json(qrels_path, {'status':'source_review_complete','illustrative':False,
        'human_adjudicated':False,'judged_by':'Documented evidence-component rubric v1',
        'rubric':'0: no explicit matching source component. 1: explicit component. No grade 2 assigned; no single record proves the full temporal question.',
        'component_relevance_only':True,
        'snapshot_sha256':manifest['snapshot_sha256'],
        'questions_sha256':hashlib.sha256((directory/'questions.json').read_bytes()).hexdigest(),
        'qrels':qrels,'judgments':judgments})
    write_json(out/'coverage.json',{'questions':coverage,
        'questions_with_components':sum(r['positive_component_records']>0 for r in coverage),
        'limitation':'Component coverage is not answerability or temporal correctness.'})
    rank(directory,qrels_path)
    score(directory,qrels_path)

    graph = records_to_graph(records)
    ledger = []
    for record in records:
        pattern = (r'\b(raised|raises|funding|financing)\b' if record['source_type']=='funding'
                   else r'\b(role|responsibilities|hiring|engineer\w*|looking for)\b')
        match = re.search(pattern,record['text'],re.I) if record['source_type']!='github' else None
        start = max(0,match.start()-100) if match else 0
        ledger.append(make_evidence_entry(record,claim_text=record['text'][start:start+300],
            extraction_method='source_excerpt',reason='Single source excerpt; no growth or causality inference.'))
    for entry in ledger:
        projection=evidence_to_graph(entry)
        graph['nodes'].extend(projection['nodes'])
        graph['edges'].extend(projection['edges'])
    write_json(out/'graph.json',graph)
    (out/'evidence.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in ledger))
    (out/'records.ttl').write_text(serialize_rdf(records))
    conforms, _, report = validate_shacl(records)
    (out/'shacl-report.txt').write_text(report)

    cohort=read_json(ROOT/'data/registry/cohort.json')
    variants={'no_graph':{'use_graph':False},'no_temporal_fields':{'use_temporal_fields':False},
              'no_corroboration_weighting':{'use_corroboration_weighting':False}}
    experiment_runs=[]
    for name, flags in variants.items():
        config=AgentConfig(mode='hybrid',encoder='hashing',demo_mode=False,**flags)
        agent=TrendScoutAgent(records,cohort=cohort,config=config,snapshot_id=manifest['snapshot_sha256'])
        bundles=[agent.answer(q['question'],requires=q.get('needs',[]),k=5,
                              question_id=q['question_id']).as_dict() for q in questions]
        path=out/(name+'.jsonl.gz')
        path.write_bytes(gzip.compress(''.join(json.dumps(b,default=str)+'\n' for b in bundles).encode(),mtime=0))
        metrics=out/(name+'-metrics.json')
        score_metrics([str(path),'--questions',str(directory/'questions.json'),
                       '--qrels',str(qrels_path),'--out',str(metrics)])
        experiment_runs.append({'name':name,'config':config.as_dict(),
            'answers_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'metrics':metrics.name})
    try:
        agreement={'status':'complete','result':annotation_agreement(directory)}
    except ValueError as exc:
        agreement={'status':'records_required','cohen_kappa':None,'reason':str(exc)}
    write_json(out/'agreement-status.json',agreement)
    write_json(out/'summary.json',{'snapshot_sha256':manifest['snapshot_sha256'],
        'shacl_conforms':conforms,'graph_nodes':len(graph['nodes']),'graph_edges':len(graph['edges']),
        'ledger_entries':len(ledger),'conditions':4,'ablations':experiment_runs,
        'saved_answers':len(questions)*7,'independent_agreement_status':agreement['status'],
        'limitation':'Hashing/extractive/in-memory measurements; component relevance is not temporal accuracy.'})
    print(json.dumps({'out':str(out),'shacl_conforms':conforms,'saved_answers':len(questions)*7}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'evaluation/mixed')
    integrate(parser.parse_args().directory)
