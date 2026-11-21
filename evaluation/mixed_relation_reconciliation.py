"""Reconcile source-assisted relation judgments without rewriting reviewer inputs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from evaluation.compute_agreement import cohen_kappa

ROOT=Path(__file__).resolve().parents[1]
OUTPUT='evaluation/mixed/relation-reconciliation.json'
POLICY={
 'LangChain':('MENTIONS','Startup','The passage explicitly names LangChain, a company in this frozen corpus. This supports a document-to-company mention, not a financing or causal edge.'),
 'LlamaParse':('MENTIONS','Product','The passage explicitly names the LlamaParse product and discusses its availability or offering. This supports a document-to-product mention.'),
 'LangSmith':('MENTIONS','Product','The passage explicitly names the LangSmith platform. This supports a document-to-product mention, not a separate-company financing claim.'),
 'Raises':('NONE',None,'Raises is a verb in the announcement heading, not a named entity or a specific funding-round node.'),
 'Series':('NONE',None,'Series alone is an incomplete round description. The fixed candidate does not identify a particular FundingRound.'),
 'Valuation':('NONE',None,'Valuation is an ordinary financial noun here, not a named entity or an identified claim node.'),
 'Follow':('NONE',None,'Follow is an imperative in a social-media prompt, not an entity.'),
 'Today':('NONE',None,'Today is a relative temporal expression, not a named entity in the permitted inventory. No event date is inferred from it.'),
 'June':('NONE',None,'June is the month in the visible publication date, not a named entity of an allowed type. Date information is distinct from a MENTIONS entity edge.'),
 'Building':('NONE',None,'Building begins a prose heading about web automation; it does not name a product, organization or other typed entity.'),
 'Paul':('NONE',None,'Paul is only the given-name fragment of the byline Paul Klein. Under the existing fragment-rejection policy it does not identify a complete Voice candidate; a full-name span would be a different candidate.'),
 'Klein':('NONE',None,'Klein is only the surname fragment of the byline Paul Klein. Under the existing fragment-rejection policy a full-name Voice would require a different candidate span.'),
 'Join':('NONE',None,'Join is an imperative in recruitment boilerplate, not a named entity or a specific JobPosting.'),
 'ABOUT':('NONE',None,'ABOUT is a section heading in recruitment boilerplate, not an entity.'),
 'THE':('NONE',None,'THE is an article inside the ABOUT THE ROLE heading, not an entity.'),
 'ROLE':('NONE',None,'ROLE is a generic heading word, not an identified JobPosting or Skill.'),
 'Don':('NONE',None,'Don is the truncated beginning of the contraction Don’t in ordinary prose, not a person or named entity.'),
 'Submit':('NONE',None,'Submit is an imperative in application instructions, not a named entity.'),
 'Pursuant':('NONE',None,'Pursuant is a preposition in legal boilerplate, not a named entity. No legal conclusion is being inferred.'),
 'Our':('NONE',None,'Our is a possessive determiner in company prose, not a named entity.'),
 'Counts':('NONE',None,'Counts is an ordinary plural noun in the reconstruction-method explanation, not a named entity, repository or identified Claim.'),
}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root=ROOT):
    base=root/'evaluation/mixed';packet_path=base/'relation-approval-packet.json'
    packet=json.loads(packet_path.read_text())
    candidates=json.loads((base/'candidate-items.json').read_text())['relations']
    expected={r['item_id']:r for r in candidates}
    if len(expected)!=len(candidates):raise ValueError('Duplicate frozen candidate identity')
    records={r['record_id']:r for r in map(json.loads,(base/'records.jsonl').read_text().splitlines())}
    reviewers={}
    for who in ['sueda','mehmet']:
        rows=packet['reviewers'][who]['decisions'];by_id={r['item_id']:r for r in rows}
        if len(by_id)!=len(rows) or set(by_id)!=set(expected):raise ValueError('Reviewer IDs do not match the frozen candidate universe')
        for key,row in by_id.items():
            candidate=expected[key]
            for field in ['document_id','subject','object']:
                if row[field]!=candidate[field]:raise ValueError('Reviewer candidate fields changed')
            if row['source_passage']!=candidate['span_text'] or row['source_url']!=records[row['document_id']]['source_url']:
                raise ValueError('Reviewer source reference changed')
            if row.get('reviewer_decision') not in {'MENTIONS','NONE'} or row.get('reviewer_confirmed') is not True:
                raise ValueError('Expected two complete confirmed documentary relation label sets')
        reviewers[who]=by_id
    decisions=[];disagreements=[];agreed_flags=[]
    for candidate in candidates:
        key=candidate['item_id'];text=records[candidate['document_id']]['text'];obj=candidate['object']
        if obj not in POLICY:raise ValueError('New object requires source-policy review: '+obj)
        start=int(key.rsplit(':',1)[-1]);span=candidate['span_text'];span_start=text.find(span)
        if text[start:start+len(obj)]!=obj or obj not in span or span_start<0 or candidate['subject']!=candidate['document_id']:
            raise ValueError('Candidate object, document subject or source passage not grounded')
        final,entity_type,reason=POLICY[obj]
        original={who:reviewers[who][key]['reviewer_decision'] for who in reviewers}
        disagree=original['sueda']!=original['mehmet']
        row={'item_id':key,'document_id':candidate['document_id'],'subject':candidate['subject'],'object':obj,
             'original_reviewer_labels':original,'reviewers_disagreed':disagree,
             'source_review_final_label':final,'object_entity_type_if_accepted':entity_type,'rationale':reason,
             'source_url':records[candidate['document_id']]['source_url'],'supporting_passage':span,
             'passage_start':span_start,'passage_end':span_start+len(span),'object_start':start,'object_end':start+len(obj),
             'source_text_sha256':hashlib.sha256(text.encode()).hexdigest()}
        decisions.append(row)
        if disagree:disagreements.append(key)
        elif original['sueda']!=final:agreed_flags.append(key)
    left={k:v['reviewer_decision'] for k,v in reviewers['sueda'].items()};right={k:v['reviewer_decision'] for k,v in reviewers['mehmet'].items()}
    degenerate=len(set(left.values())|set(right.values()))==1
    kappa=None if degenerate else cohen_kappa(left,right)[0]
    signoff_path=base/'relation-reconciliation-signoff.json'
    signoff=json.loads(signoff_path.read_text()) if signoff_path.exists() else None
    if signoff is not None:
        if signoff.get('independent_annotation_claimed') is True or signoff.get('kappa_eligible') is True:
            raise ValueError('Reconciliation signoff cannot claim independent annotation or kappa eligibility')
        if signoff.get('status')!='joint_final_label_endorsement':
            raise ValueError('Unexpected reconciliation signoff status')
    inputs=[packet_path,base/'records.jsonl',base/'candidate-items.json',base/'guidelines.json',base/'sueda-source-review/decision-plan.json',root/'evaluation/mixed_relation_reconciliation.py']
    if signoff_path.exists():
        inputs.append(signoff_path)
    return {'status':'source_assisted_reconciliation_complete','method':'Exact frozen source review under the existing named-entity and fragment-rejection policy.',
            'reviewer_decisions_preserved':True,'is_independent_gold_standard':False,'personal_adjudicator_signoff':signoff,
            'scope':'The final-label field is a source-assisted reconciliation output, not a replacement for either reviewer’s original decisions or an assertion of human independent adjudication.',
            'policy':'MENTIONS requires an explicit mention of an allowed typed entity; headings, pronouns, ordinary nouns and underspecified name fragments are NONE. Subject/object spans are fixed. No label is chosen to improve kappa.',
            'pre_reconciliation_agreement':{'shared_items':len(left),'matching_labels':len(left)-len(disagreements),'raw_agreement':(len(left)-len(disagreements))/len(left),
                'cohen_kappa':kappa,'undefined_reason':'single observed label category' if degenerate else None,
                'interpretation':'Descriptive agreement of the supplied source-assisted personal judgments, computed before reconciliation.'},
            'summary':{'items_reviewed':len(decisions),'reviewer_disagreements_reviewed':len(disagreements),
                'disagreement_resolution_label_counts':dict(Counter(r['source_review_final_label'] for r in decisions if r['reviewers_disagreed'])),
                'agreed_labels_flagged_by_source_review':len(agreed_flags),'all_source_review_label_counts':dict(Counter(r['source_review_final_label'] for r in decisions))},
            'disagreement_ids':disagreements,'agreed_label_quality_flag_ids':agreed_flags,'decisions':decisions,
            'input_sha256':{str(p.relative_to(root)):sha(p) for p in inputs}}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args();result=build();out=ROOT/OUTPUT
    if a.check:
        if json.loads(out.read_text())!=result:raise SystemExit('Reconciliation differs from current source inputs; rebuild and review.')
    else:out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'summary':result['summary'],'pre_reconciliation_agreement':result['pre_reconciliation_agreement']},indent=2))


if __name__=='__main__':main()
