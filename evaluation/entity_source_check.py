"""Formal entity checks and explicit source-context corrections; no rater edits."""
from collections import Counter
import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUTPUT='evaluation/submission/sueda-entity-source-check.json'
# Source-context findings from the current release excerpts, not count targets.
REJECT={
 'EOL':'Lifecycle abbreviation for end-of-life; it describes a support status rather than a Technology entity.',
 'Fix':'Imperative/change-list prefix, not a named technology.',
 'Multimodal':'An adjective describing synthesis/reranking here, not an identified technology name.',
 'Preserve':'An imperative introducing a change description, not a technology.',
 'URL-backed':'An adjective qualifying video/document blocks, not a standalone named technology.',
 'Breaking':'An adjective in a breaking-change description, not an entity.',
 'Message':'A generic fragment of the Message Block Buffer Resolution heading, not a complete named identifier.',
 'Block':'A generic fragment of the Message Block Buffer Resolution heading, not a complete named identifier.',
 'Bugfix':'A change-list prefix, not a technology.',
 'Integration':'A heading prefix; the named integration is AgentMesh, not Integration.',
 'Agents':'A generic plural in an integration title, not a specific named entity.',
 'Conversation':'An incomplete generic fragment of a conversation/context description, not an identified technology.',
 'Context':'An incomplete generic fragment of a conversation/context description, not an identified technology.',
 'Element':'A generic fragment in an Element node-parser description, not a complete qualified API identifier.',
 'Isolate':'An imperative describing a change, not a named technology.',
 'Restrict':'An imperative describing allowed image formats, not a technology.',
 'Trace':'An imperative describing route tracing, not an identified tool name.',
 'Documentation':'A release-note section heading, not a named Document.',
 'Contributors':'A release-note section heading, not a named Document.',
 'Tag':'An imperative about tagging evaluation spans, not a Document.',
 'Record':'An imperative about recording errors or execution state, not a Document.',
 'Document':'An imperative about documenting agent planning, not a named Document.',
 'Report':'An imperative about reporting token usage, not a named Document.',
}
RETYPED={
 'Responses':('Technology','Responses refers to the named API/tool-call interface in this context, not a document.'),
 'Decisions':('Technology','The passage explicitly qualifies Decisions with API; Document is not the supported type.'),
}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def build(root=ROOT):
    results={};inputs={}
    for round_name in ['real','mixed']:
        base=root/'evaluation'/round_name;p=base/'workbooks/sueda-entities.csv'
        rows=list(csv.DictReader(p.open()));guide=json.loads((base/'guidelines.json').read_text());candidates=json.loads((base/'candidate-items.json').read_text())['entities']
        by_id={c['item_id']:c for c in candidates};docs={r['record_id']:r for r in map(json.loads,(base/'records.jsonl').read_text().splitlines())}
        if len({r['item_id'] for r in rows})!=len(rows) or {r['item_id'] for r in rows}!=set(by_id):raise ValueError('Entity candidate identity mismatch')
        final=[];corrections=[]
        for row in rows:
            c=by_id[row['item_id']];text=docs[row['document_id']]['text'];start=int(row['start']);end=int(row['end'])
            if row['label'] not in set(guide['entity_types'])|{'NONE'} or text[start:end]!=row['entity_text'] or row['span_text'] not in text:
                raise ValueError('Entity label/span invalid')
            if any(row[k]!=str(c[k]) for k in ['document_id','start','end','entity_text','span_text']):raise ValueError('Entity candidate fields changed')
            value=row['label'];reason=None
            if round_name=='real' and value!='NONE':
                if row['entity_text'] in REJECT:value='NONE';reason=REJECT[row['entity_text']]
                elif row['entity_text'] in RETYPED and row['label']=='Document':value,reason=RETYPED[row['entity_text']]
            record={'item_id':row['item_id'],'document_id':row['document_id'],'entity_text':row['entity_text'],
                'original_source_label':row['label'],'source_review_final_label':value,'start':start,'end':end,
                'supporting_passage':row['span_text'],'source_url':docs[row['document_id']]['source_url']}
            final.append(record)
            if value!=row['label']:corrections.append({**record,'rationale':reason})
        results[round_name]={'formally_valid_candidates':len(rows),'stored_positive_labels':sum(r['label']!='NONE' for r in rows),
            'source_review_positive_labels':sum(r['source_review_final_label']!='NONE' for r in final),
            'source_review_label_counts':dict(Counter(r['source_review_final_label'] for r in final)),
            'recommended_corrections':len(corrections),'corrections':corrections,'source_review_labels':final}
        for path in [p,base/'guidelines.json',base/'candidate-items.json',base/'records.jsonl']:inputs[str(path.relative_to(root))]=sha(path)
    inputs['evaluation/entity_source_check.py']=sha(root/'evaluation/entity_source_check.py')
    return {'method':'Source-assisted validation and documented context corrections; original worksheets and personal judgments are preserved.',
        'scope':'Formal ID, allowed-label and source-span checks cover both seed pools. Semantic corrections concern identified release-note heading, fragment, lifecycle and imperative errors; other stored labels are carried forward, not independently re-annotated.',
        'is_independent_annotation':False,'count_targets_used_to_choose_labels':False,'rounds':results,'input_sha256':inputs}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args();r=build();out=ROOT/OUTPUT
    if a.check:
        if json.loads(out.read_text())!=r:raise SystemExit('Entity source check differs from current inputs.')
    else:out.write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:{n:v for n,v in r['rounds'][k].items() if n not in ['corrections','source_review_labels']} for k in r['rounds']},indent=2))


if __name__=='__main__':main()
