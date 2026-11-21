"""Source-assisted funding review and conservative temporal joins over frozen data."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = 'evaluation/submission/funding-source-review.json'
DECISIONS = {
 'langchain': dict(announcement_date='2026-11-13', date_quote='November 13, 2026',
  round_quote='Today, we’re announcing that LangChain raised $300M at a $3B valuation',
  investors_quote='The round was led by existing investor CapitalG, with significant participation from new investors GIC and DFJ Growth and existing investors IVP and Sapphire Ventures.',
  round='Series C', amount_usd=300000000, lead='CapitalG', participants=['GIC','DFJ Growth','IVP','Sapphire Ventures'],
  round_label_quote='Our Series C Announcement'),
 'llamaindex': dict(announcement_date=None, date_quote=None,
  round_quote='our $19M series A funding round',
  investors_quote='Our series A is led by Norwest Venture Partners, with participation from our existing investors Greylock Partners',
  round='Series A', amount_usd=19000000, lead='Norwest Venture Partners', participants=['Greylock Partners'],round_label_quote='our $19M series A funding round'),
 'browserbase': dict(announcement_date='2025-06-18', date_quote='June 18, 2025',
  round_quote='The product release coincides with a $40 million Series B financing round led by Notable Capital, with participation from existing investors CRV and Kleiner Perkins.',
  investors_quote='led by Notable Capital, with participation from existing investors CRV and Kleiner Perkins',
  round='Series B', amount_usd=40000000, lead='Notable Capital', participants=['CRV','Kleiner Perkins'],round_label_quote='Series B financing round'),
}


def sha(path):
 return hashlib.sha256(path.read_bytes()).hexdigest()


def passage(text, quote):
 if quote is None:
  return None
 start=text.find(quote)
 if start<0:
  raise ValueError('Reviewed quotation no longer matches frozen text: '+quote)
 return dict(text=quote,start=start,end=start+len(quote))


def build(root=ROOT):
 funding_path='evaluation/mixed/records.jsonl'
 github_path='evaluation/cohort-history-v2/records.jsonl'
 jobs_paths=['evaluation/cohort-job-history/records.jsonl','evaluation/cohort-archive-followup/job-records.jsonl']
 funding=[r for r in map(json.loads,(root/funding_path).read_text().splitlines()) if r['source_type']=='funding']
 github=list(map(json.loads,(root/github_path).read_text().splitlines()))
 jobs=[]
 for p in jobs_paths:
  jobs.extend(map(json.loads,(root/p).read_text().splitlines()))
 inputs=[funding_path,github_path]+jobs_paths
 rows=[]
 if {r['company_id'] for r in funding} != set(DECISIONS):
  raise ValueError('Funding source set changed; review decisions.')
 for r in funding:
  company=r['company_id']; d=DECISIONS[company]; text=r['text']; date=d['announcement_date']
  html='evaluation/mixed/sources/'+company+'-funding.html';inputs.append(html)
  spans={key:passage(text,d[key]) for key in ['date_quote','round_quote','investors_quote','round_label_quote']}
  board_dates=sorted(set(j['metadata']['source_snapshot_at'][:10] for j in jobs if j['company_id']==company))
  strictly_later=[g['record_id'] for g in github if g['company_id']==company and date and g['metadata']['activity_window']['start'][:10]>date]
  in_window=bool(date and '2025-11-01'<=date<='2026-11-21') if date else None
  rows.append(dict(company_id=company,record_id=r['record_id'],source_url=r['source_url'],source_file=funding_path,
   source_html=html,source_html_sha256=sha(root/html),text_sha256=hashlib.sha256(text.encode()).hexdigest(),
   source_record_content_hash=r['content_hash'],review_method='source_assisted_exact_passage_review',independent_personal_annotation=False,
   announcement_date=date,date_precision='day' if date else None,announcement_within_study_window=in_window,
   financing_closed_at=None,event_time_limit='An announcement date does not establish the legal closing date. Unknown dates remain null.',
   round=d['round'],amount_usd=d['amount_usd'],lead_investor=d['lead'],participating_investors_in_cited_passage=d['participants'],
   investor_list_scope='Participants in cited passage only; not a claim of an exhaustive cap table.',passages=spans,
   observed_at=r['observed_at'],original_published_at=r.get('published_at'),original_event_at=r.get('event_at'),
   retained_complete_github_windows_strictly_after_announcement=strictly_later,
   complete_board_snapshot_dates=board_dates,
   post_announcement_board_snapshot_dates=[t for t in board_dates if date and t>date],
   temporal_conclusion=('Unknown announcement date prevents ordering.' if not date else
    'Announcement is outside the defined study window; retain as historical context only.' if not in_window else
    'No complete retained post-announcement commit week and no two retained post-announcement job snapshots; a later increase is not established.'),
   funding_caused_growth_established=False))
 return dict(scope='Three frozen primary funding pages reviewed on behalf of the team; original records, scored qrels and personal reviewer files are unchanged.',
  method='Exact source-text spans with source hashes; normalized announcement days only. No invented financing close dates or independent reviewer attestations.',
  input_sha256={p:sha(root/p) for p in inputs},reviews=rows,
  summary=dict(funding_pages=len(rows),dated_announcements=sum(bool(r['announcement_date']) for r in rows),
   announcements_in_study_window=sum(r['announcement_within_study_window'] is True for r in rows),
   unknown_announcement_dates=sum(r['announcement_date'] is None for r in rows),full_funding_to_later_growth_paths_established=0))


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args();r=build();out=ROOT/OUTPUT
 if a.check:
  if json.loads(out.read_text())!=r:
   raise SystemExit('Funding review differs from current frozen inputs.')
 else:
  out.write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
 print(json.dumps(r['summary'],indent=2))


if __name__=='__main__':
 main()
