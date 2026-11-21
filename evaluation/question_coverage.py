"""Offline source inventory and coverage assessment; never writes benchmark labels."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = 'evaluation/submission/question-coverage.json'
PACKS = {
    'github': 'evaluation/cohort-history-v2/records.jsonl',
    'jobs': 'evaluation/cohort-job-history/records.jsonl',
    'jobs_archive': 'evaluation/cohort-archive-followup/job-records.jsonl',
    'voice': 'evaluation/sueda-evidence-extension/public-voice-records.jsonl',
    'documentary': 'evaluation/sueda-delivery-corpus/study-records.jsonl',
    'mixed_context': 'evaluation/mixed/records.jsonl',
}
EXPECTED_QUESTION_IDS = ['q-pilot-github-mlops', 'q-investors-later-hiring', 'q-sector-attention', 'q-why-emerging', 'q-unsupported-acquisition', 'q-future-performance', 'q-langchain-github-since-september', 'q-crewai-activity-eight-weeks', 'q-startups-multi-signal-ten-weeks', 'q-funding-after-hiring', 'q-sector-multi-origin', 'q-company-slowed-commits', 'q-llamaindex-retrieval-postings', 'q-e2b-sandbox-coverage', 'q-browserbase-agent-activity', 'q-composio-tool-postings', 'q-letta-memory-coverage', 'q-langfuse-observability-signals', 'q-haystack-rag-hiring', 'q-funding-before-github-growth', 'q-missing-funding-langsmith', 'q-outside-collection-window', 'q-future-acquisition', 'q-undocumented-private-metrics', 'q-emerging-change-label', 'q-disputed-technical-claim', 'q-stale-source-label', 'q-independent-origin-definition']

# Editorial coverage judgments: requirements, source families, company scope, limit.
SPECS = [
 ('partial_evidence',['github','jobs'],[], 'Match dated new MLOps roles to rising commit windows.', 'Complete official-population histories cover 13 companies; four additional paired channels are limited to directory or parent-brand-title populations. Intervals are irregular; role-specific MLOps increases and an eight-week paired hiring baseline remain unestablished.'),
 ('partial_evidence',['funding','jobs'],[], 'Resolve investor-to-round-to-company-to-later-role paths.', 'Funding event dates and comparable skill-specific before/after job stocks are not established cohort-wide.'),
 ('partial_evidence',['voice','github','jobs'],[], 'Compare dated sector attention across independent voices and operational windows.', 'Five articles from two publishers are selected coverage, without a stable attention baseline or adjudicated sector/claim independence.'),
 ('policy_only',[],[], 'Explain emerging and its transition using claim-specific ledger evidence.', 'The policy is available; this coverage inventory does not establish a named company ledger state.'),
 ('abstention_supported',[],[], 'Require direct evidence of the specified 2024 acquisition.', 'The retained corpus does not establish this acquisition; absence here is not proof of worldwide non-occurrence.'),
 ('abstention_supported',[],[], 'Require knowledge of future 2027 valuation.', 'Observed sources cannot establish the requested future outcome.'),
 ('partial_evidence',['github','jobs'],['langchain'], 'Compare commit and job baselines beginning in September.', 'Commit windows begin September 21; the earliest retained board snapshot is October 5, so the full September comparison is unavailable.'),
 ('bounded_operational_calculation',['github'],['crewai'], 'State a precise commit metric and compare eight complete weeks.', 'Endpoint and half-window comparisons measure different aspects; neither is a statistical trend test or a measure of all repository activity.'),
 ('partial_evidence',['github','jobs'],[], 'Compare both signals across ten complete weeks.', 'Only eight complete commit weeks are retained; ten-week paired hiring baselines are unavailable.'),
 ('partial_evidence',['funding','jobs'],[], 'Establish funding event time preceding an increase in relevant roles.', 'Publication or retrieval time cannot substitute for funding event time; current role mentions alone do not show hiring increases.'),
 ('partial_evidence',['voice','documentary'],[], 'Adjudicate sector associations and at least two independent origins per claim.', 'Publisher diversity is observable, but company passages are not independent documents and claim-level independence/sector labels are not adjudicated.'),
 ('bounded_operational_calculation',['github'],[], 'Define last month and compare repository commit counts.', 'Use the last four complete ISO weeks, first two versus last two; this is a bounded descriptive proxy, not a rolling calendar month or company-wide slowdown.'),
 ('partial_evidence',['jobs'],['llamaindex'], 'Compare retrieval-role stock over the latest observed quarter.', 'Two archived official career lists and a current list show specific-role stock declining from 8 to 2. They do not establish quarter-wide retrieval-role additions without role-level source review.'),
 ('partial_evidence',['voice','documentary'],['e2b'], 'Compare E2B sandbox coverage over a consistent sampling window.', 'Dated commentary is available; a stable before/after news and voice collection baseline is not.'),
 ('partial_evidence',['github','voice','documentary'],['browserbase'], 'Align rising commits with dated browser-automation attention.', 'Commit history exists; the selected voice extension has no Browserbase passage. Broader documentary mentions require claim-specific review.'),
 ('partial_evidence',['jobs'],['composio'], 'Compare agent-tooling/developer-platform roles across board snapshots.', 'Composio has retained board baselines: 30 to 30 from October 13, and 31 to 30 from November 6. These totals do not establish an increase in the specified role category.'),
 ('partial_evidence',['github','jobs','voice','documentary'],['letta'], 'Review direct evidence for and against a specific memory-product claim.', 'Repository counts and current jobs do not themselves validate memory-product claims; direct claim-specific supporting and conflicting passages require review.'),
 ('partial_evidence',['github','jobs'],['langfuse'], 'Pair commit growth with company-attributed observability hiring growth.', 'Langfuse-title roles in the parent ClickHouse board rise from 11 on October 17 to 13 on November 21. This is a branded-title subset, not full company hiring or a weekly skill-specific trajectory; align it with the defined commit windows before answering.'),
 ('partial_evidence',['jobs'],['deepset'], 'Compare dated RAG/NLP engineering role stock.', 'deepset has a July 22 baseline of 3 postings versus 4 current postings. Newly observed role IDs include engineering and commercial roles; RAG/NLP skill relevance requires direct description review.'),
 ('partial_evidence',['funding','github'],[], 'Resolve funding event dates and comparable later activity windows.', 'Three funding pages provide context; event dates remain unnormalized. Publication dates do not establish funding dates or causality.'),
 ('abstention_supported',['funding'],['langchain'], 'Resolve LangSmith product versus legal company and a directly evidenced round lead.', 'Do not substitute a LangChain financing page for an independently established LangSmith funding round.'),
 ('abstention_supported',[],['crewai'], 'Require market-share measurements before November 1, 2025.', 'No retained market-share evidence covers the requested period.'),
 ('abstention_supported',[],[], 'Require evidence of a future acquisition.', 'The requested future outcome cannot be established from observed sources.'),
 ('abstention_supported',[],['langchain'], 'Require authorized, documented quarterly private revenue measurements.', 'No such private revenue measurements are retained.'),
 ('policy_only',[],[], 'Explain why one positive origin need not establish corroboration.', 'Use origin control and claim-specific support; no new company-state judgment is made.'),
 ('policy_only',[],[], 'Explain material conflicting evidence and a disputed transition.', 'A hypothetical policy transition is not evidence that a real company claim is disputed.'),
 ('policy_only',[],[], 'Explain staleness using supersession, refresh expectations or validity.', 'Age alone does not force stale; a claim-specific validity or refresh basis is needed.'),
 ('policy_only',[],[], 'Explain syndicated-copy origin clustering.', 'Copies under common origin/control are not additional independent corroboration.'),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root=ROOT):
    questions = json.loads((root/'evaluation/real/questions.json').read_text())['questions']
    if [q['question_id'] for q in questions] != EXPECTED_QUESTION_IDS or len(questions) != len(SPECS):
        raise ValueError('Question set changed: review coverage specifications.')
    inputs = list(PACKS.values()) + ['evaluation/real/questions.json', 'docs/source-policy.md', 'evaluation/submission/funding-source-review.json', 'evaluation/cohort-history-followup/review.json', 'evaluation/cohort-ats-history/review.json', 'evaluation/remaining-history-discovery/review.json']
    records = []
    for pack, name in PACKS.items():
        for r in map(json.loads, (root/name).read_text().splitlines()):
            # Avoid old mixed GitHub histories and duplicate LangChain job samples.
            if pack == 'mixed_context' and not (r['source_type'] == 'funding' or (r['source_type'] == 'job' and r['company_id'] == 'llamaindex')):
                continue
            records.append(dict(record_id=r['record_id'], company_id=r['company_id'],
                family={'public_voice':'voice','company':'documentary','news':'documentary','job':'jobs'}.get(r['source_type'],r['source_type']),
                source_file=name, source_url=r['source_url'], content_hash=r['content_hash'],
                published_at=r.get('published_at'), event_at=r.get('event_at'), observed_at=r.get('observed_at'),
                publisher=r.get('publisher'), activity_window=r.get('metadata',{}).get('activity_window')))
    ids = [r['record_id'] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate source record IDs in coverage inventory')
    weeks = defaultdict(list)
    for r in records:
        if r['family']=='github':
            w=r['activity_window']; weeks[r['company_id']].append(dict(end=w['end'], commits=w['commit_count'], record_id=r['record_id']))
    calculations = {}
    for company, points in sorted(weeks.items()):
        points.sort(key=lambda x:x['end'])
        if len(points)!=8:
            raise ValueError('Expected eight frozen commit weeks per company')
        values=[p['commits'] for p in points]
        calculations[company]=dict(weeks=points, first_week=values[0], last_week=values[-1],
            endpoint_change=values[-1]-values[0], first_four_total=sum(values[:4]), last_four_total=sum(values[4:]),
            last_month_first_two_total=sum(values[-4:-2]),last_month_last_two_total=sum(values[-2:]),
            last_month_change=sum(values[-2:])-sum(values[-4:-2]))
    rows=[]
    for q, (status,families,companies,requirement,limit) in zip(questions,SPECS):
        selected=[r['record_id'] for r in records if r['family'] in families and (not companies or r['company_id'] in companies)]
        rows.append(dict(**q,coverage_status=status,requirement=requirement,evidence_record_ids=selected,
            evidence_selection='Candidate components only; inclusion does not establish relevance or full answerability.',
            career_history_reference='evaluation/cohort-history-followup/review.json' if 'jobs' in families else None,
            ats_history_reference='evaluation/cohort-ats-history/review.json' if 'jobs' in families else None,
            remaining_history_reference='evaluation/remaining-history-discovery/review.json' if 'jobs' in families else None,
            scope_companies=companies or 'cohort',source_families=families,limitation=limit,
            funding_review_reference='evaluation/submission/funding-source-review.json' if 'funding' in families else None,
            policy_reference='docs/source-policy.md' if status=='policy_only' else None))
    voice=[r for r in records if r['family']=='voice']
    return dict(schema_version=1, scope='Offline follow-up coverage assessment of the original 28 questions; not scored evaluation, qrels, independent annotation or a new collection.',
        study_as_of='2026-11-21', source_window='Frozen documentary window starts 2025-11-01; commit weeks cover 2026-09-21 through 2026-11-15. Each record retains its own source clocks.',
        input_sha256={p:digest(root/p) for p in inputs},
        summary=dict(question_count=len(rows),status_counts=dict(Counter(r['coverage_status'] for r in rows)),
            inventory_record_count=len(records),family_counts=dict(Counter(r['family'] for r in records)),
            github_companies=len(weeks),voice_articles=len(set(r['source_url'] for r in voice)),
            voice_publishers=sorted(set(r['publisher'] for r in voice))),
        interpretation_rules=['Unknown coverage is not zero activity.', 'Current job stock and role mentions do not establish hires or increases.',
            'Publication, event and observation times are distinct.', 'Publisher diversity alone does not establish independent corroboration of a claim.',
            'Company and repository signal series overlap; commit calculations use raw records once, including observed zero-count weeks.',
            'Bounded comparisons are descriptive; no significance, causal inference or full temporal benchmark accuracy is claimed.'],
        questions=rows,commit_calculations=calculations,source_records=records)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args(); result=build(); output=ROOT/OUTPUT
    if args.check:
        if json.loads(output.read_text())!=result:
            raise SystemExit('Coverage artifact differs from current frozen inputs; rebuild and review.')
    else:
        output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(result['summary'],indent=2))


if __name__=='__main__':
    main()
