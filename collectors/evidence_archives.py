"""Freeze dated public commentary and comparable archived/current job boards.

Earlier experiment snapshots are never overwritten. Archive capture time and
current retrieval time remain distinct; posting-count change is not hiring.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

import requests

from collectors.cohort import alias_index, included_companies, load_cohort, match_companies
from collectors.common import job_fields, plain_text
from collectors.records import make_record, parse_datetime, utc_now, validate_records
from signals.job_features import role_families

VOICES = [
    ('simon_sprites', 'Simon Willison', 'https://simonwillison.net/2026/Jan/9/sprites-dev/'),
    ('simon_liteparse', 'Simon Willison', 'https://simonwillison.net/2026/Apr/23/liteparse-for-the-web/'),
    ('latent_artifice', 'Latent Space', 'https://www.latent.space/p/ainews-truth-in-the-time-of-artifice'),
    ('latent_pull_requests', 'Latent Space', 'https://www.latent.space/p/ainews-rip-pull-requests-2005-2026'),
    ('latent_manifesto', 'Latent Space', 'https://www.latent.space/p/ainews-the-no-ai-slop-manifesto'),
]
BOARD = 'https://api.ashbyhq.com/posting-api/job-board/langchain'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ArticleText(HTMLParser):
    """Read visible text only from an article or Simon's entry container."""
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

    def __init__(self, use_article):
        super().__init__(convert_charrefs=True)
        self.use_article=use_article
        self.level=0
        self.root=None
        self.hidden=0
        self.parts=[]

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag not in self.VOID:self.level+=1
        if self.root is None and ((self.use_article and tag=='article') or
            (not self.use_article and tag=='div' and 'entryPage' in attrs.get('class','').split())):
            self.root=self.level
        if tag in {'script','style','nav','footer'}:self.hidden+=1
        if self.root is not None and tag in {'p','li','h1','h2','h3','h4','br'}:self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script','style','nav','footer'}:self.hidden=max(0,self.hidden-1)
        if self.root is not None and self.level==self.root:self.root=None
        if tag not in self.VOID:self.level=max(0,self.level-1)

    def handle_data(self, data):
        if self.root is not None and not self.hidden:self.parts.append(data)


def article(html_text):
    title_match=re.search(r'<meta\s+(?:property|name)=["\']og:title["\']\s+content=["\']([^"\']+)',html_text,re.I)
    if not title_match:title_match=re.search(r'<title[^>]*>(.*?)</title>',html_text,re.S|re.I)
    title=html.unescape(title_match.group(1)) if title_match else None
    parser=ArticleText('<article' in html_text.lower());parser.feed(html_text)
    text=' '.join(''.join(parser.parts).split())
    if not text or len(text)<100:raise ValueError('substantial public article body not found')
    date=re.search(r'"datePublished"\s*:\s*"([^"<>]+)"',html_text)
    if date:
        published=parse_datetime(html.unescape(date.group(1)))
        basis='Source structured datePublished timestamp'
        precision='second'
    else:
        # The visible Posted day establishes a date, not an exact UTC instant.
        posted=re.search(r'Posted\s+(\d{1,2})(?:st|nd|rd|th)\s+(\w+)\s+(\d{4})',plain_text(html_text))
        if not posted:raise ValueError('publication date absent; update time is not a substitute')
        day=datetime.strptime(' '.join(posted.groups()),'%d %B %Y')
        published=day.strftime('%Y-%m-%dT00:00:00Z')
        basis='Visible Posted date; UTC midnight normalizes a date-only value and is not a measured publication time.'
        precision='day'
    if not published:raise ValueError('invalid source publication timestamp')
    return {'title':title,'text':text,'published_at':published,'publication_basis':basis,'publication_precision':precision}


def public_voice_records(page, source_url, publisher, observed_at, cohort):
    aliases=alias_index(included_companies(cohort))
    matches=match_companies(page['title']+' '+page['text'],aliases)
    records=[]
    for company_id, company_name in matches:
        patterns=[p for cid,_,p in aliases if cid==company_id]
        positions=[m.start() for pattern in patterns if (m:=pattern.search(page['text']))]
        if not positions:continue
        start=max(0,min(positions)-180)
        passage=page['text'][start:min(len(page['text']),min(positions)+1000)]
        records.append(make_record(source_type='public_voice',source_url=source_url,
            title=f"{page['title']} — {company_name} passage",text=passage,publisher=publisher,
            company_id=company_id,startup_name=company_name,published_at=page['published_at'],
            observed_at=observed_at,event_type='public_commentary',collector_version='evidence-archives/1.0',
            access_note='Public article; locally retained passage and raw HTML. Publisher rights retained.',
            metadata={'article_title':page['title'],'matched_company_ids':[cid for cid,_ in matches],
                'publication_basis':page['publication_basis'],'publication_precision':page['publication_precision'],
                'source_control_group':'publisher:'+publisher.casefold(),
                'documentary_scope':'Public attention/commentary; not independent financial confirmation.',
                'article_text_sha256':sha(page['text'].encode())}))
    if not records:raise ValueError('article does not contain a retained cohort passage')
    return records


def listed_jobs(payload, snapshot_at):
    if not isinstance(payload,dict) or not isinstance(payload.get('jobs'),list):
        raise ValueError('complete Ashby jobs array required')
    jobs=payload['jobs']
    ids=[j.get('id') for j in jobs]
    if not all(isinstance(i,str) and i for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('missing or duplicated posting IDs')
    for job in jobs:
        if not job.get('jobUrl','').startswith('https://jobs.ashbyhq.com/langchain/'):
            raise ValueError('unexpected board/company posting URL')
        published=parse_datetime(job.get('publishedAt'))
        if published and published>snapshot_at:raise ValueError('posting publication is after its capture')
    return [j for j in jobs if j.get('isListed',True) is True]


def job_records(payload, source_url, snapshot_at, retrieved_at, archive_capture=None):
    records=[]
    for job in listed_jobs(payload,snapshot_at):
        description=job.get('descriptionPlain') or plain_text(job.get('descriptionHtml'))
        metadata=job_fields(job['title'],description)
        metadata.update(source_record_id='ashby:langchain:'+job['id'],source_snapshot_at=snapshot_at,
            source_job_url=job['jobUrl'],location=job.get('location'),team=job.get('team'),
            collector='ashby_archive',source_control_group='company:langchain',archive_capture=archive_capture,
            role_families=list(role_families(job['title'])),
            snapshot_scope='Listed posting at the documented snapshot; no actual hire inferred.')
        record=make_record(source_type='job',source_url=source_url,title=job['title'],
            text=' '.join(p for p in [job['title'],job.get('location'),description] if p),
            publisher='LangChain',startup_name='LangChain',company_id='langchain',
            published_at=job.get('publishedAt'),event_at=snapshot_at,observed_at=retrieved_at,
            event_type='job_board_observation',collector_version='evidence-archives/1.0',metadata=metadata)
        # A posting observed twice remains two observations, with one stable posting ID.
        record['record_id']='ashby-observation:langchain:'+job['id']+':'+sha((source_url+snapshot_at).encode())[:16]
        records.append(record)
    return records


def compare_boards(before,after,before_at,after_at):
    old={j['id']:j for j in listed_jobs(before,before_at)}
    new={j['id']:j for j in listed_jobs(after,after_at)}
    def families(jobs):
        return dict(Counter(f for j in jobs.values() for f in role_families(j['title'])))
    old_f,new_f=families(old),families(new)
    return {'company_id':'langchain','baseline_snapshot_at':before_at,'latest_snapshot_at':after_at,
        'baseline_listed_postings':len(old),'latest_listed_postings':len(new),
        'net_posting_change':len(new)-len(old),'newly_observed_ids':sorted(new.keys()-old.keys()),
        'no_longer_observed_ids':sorted(old.keys()-new.keys()),'retained_ids':len(new.keys()&old.keys()),
        'baseline_title_role_families':old_f,'latest_title_role_families':new_f,
        'title_family_changes':{f:new_f.get(f,0)-old_f.get(f,0) for f in sorted(old_f.keys()|new_f.keys())},
        'interpretation':'Two complete board observations; differences measure listed postings, not hires, filled positions, causality, or a weekly growth trajectory.'}


def replay(out):
    """Rebuild normalized evidence from the frozen raw sources, offline."""
    manifest=json.loads((out/'manifest.json').read_text())
    sources={Path(s['file']).name:s for s in manifest['sources']}
    for source in sources.values():
        if sha((out/source['file']).read_bytes())!=source['sha256']:
            raise ValueError('raw source checksum mismatch')
    for name,digest in manifest['output_sha256'].items():
        if sha((out/name).read_bytes())!=digest:raise ValueError('normalized output checksum mismatch')
    cohort=json.loads((out/'cohort.json').read_text())
    if sha((out/'cohort.json').read_bytes())!=manifest['cohort_sha256']:
        raise ValueError('cohort checksum mismatch')
    voices=[]
    for source_id,publisher,_ in VOICES:
        source=sources[source_id+'.html']
        page=article((out/source['file']).read_text())
        voices.extend(public_voice_records(page,source['response_url'],publisher,manifest['observed_at'],cohort))
    archive=manifest['archive_capture']
    old_source=sources['langchain-archived.json']
    if parsedate_to_datetime(old_source['memento_datetime']).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')!=archive['captured_at']:
        raise ValueError('archive capture provenance mismatch')
    if archive['payload_sha256']!=old_source['sha256'] or archive['url']!=old_source['response_url']:
        raise ValueError('archive source binding mismatch')
    old=json.loads((out/old_source['file']).read_text())
    current_source=sources['langchain-current.json']
    current=json.loads((out/current_source['file']).read_text())
    current_at=current_source['retrieved_at']
    jobs=job_records(old,old_source['response_url'],archive['captured_at'],manifest['observed_at'],archive)
    jobs+=job_records(current,BOARD,current_at,current_at)
    stored=lambda name:[json.loads(line) for line in (out/name).read_text().splitlines() if line.strip()]
    if voices!=stored('public-voice-records.jsonl') or jobs!=stored('job-observations.jsonl'):
        raise ValueError('replayed records differ from frozen normalized evidence')
    if validate_records(voices+jobs):raise ValueError('invalid normalized evidence')
    comparison=compare_boards(old,current,archive['captured_at'],current_at)
    if comparison!=json.loads((out/'hiring-comparison.json').read_text()):
        raise ValueError('posting comparison differs from source snapshots')
    return {'status':'offline_replay_verified','public_voice_documents':manifest['public_voice_documents'],
        'public_voice_associations':len(voices),'job_observations':len(jobs),
        'net_posting_change':comparison['net_posting_change']}


def collect(out):
    if out.exists():raise ValueError('refusing to overwrite evidence extension')
    out.mkdir(parents=True);(out/'sources').mkdir()
    observed=utc_now();sources=[];records=[];articles=[]
    def fetch(name,url):
        r=requests.get(url,timeout=45,headers={'User-Agent':'TrendScout-coursework/1.0'})
        r.raise_for_status();path=out/'sources'/name;path.write_bytes(r.content)
        sources.append({'file':'sources/'+name,'url':url,'response_url':r.url,
            'retrieved_at':utc_now(),'sha256':sha(r.content),'memento_datetime':r.headers.get('Memento-Datetime')})
        return r
    cohort=load_cohort()
    (out/'cohort.json').write_text(json.dumps(cohort,indent=2)+'\n')
    for source_id,publisher,url in VOICES:
        response=fetch(source_id+'.html',url);page=article(response.text)
        if not '2025-11-01'<=page['published_at'][:10]<='2026-11-21':
            raise ValueError('voice publication outside declared extension window')
        new=public_voice_records(page,response.url,publisher,observed,cohort)
        records.extend(new);articles.append({'source_id':source_id,'source_url':response.url,
            'publisher':publisher,**page,'association_records':len(new)})
        print(source_id,page['published_at'],len(new),'cohort passages',flush=True)
    cdx_url='https://web.archive.org/cdx/search/cdx'
    params='?url='+BOARD+'&output=json&filter=statuscode:200&collapse=timestamp:6&from=2025&to=2026&limit=12'
    cdx=fetch('langchain-cdx.json',cdx_url+params).json()
    if not cdx:raise ValueError('no complete archived board capture available')
    entries=[dict(zip(cdx[0],row)) for row in cdx[1:]]
    selected=min(entries,key=lambda e:e['timestamp'])
    if selected['original']!=BOARD:raise ValueError('archive index changed original board URL')
    archive_url=f"https://web.archive.org/web/{selected['timestamp']}id_/{BOARD}"
    old=fetch('langchain-archived.json',archive_url)
    memento=old.headers.get('Memento-Datetime')
    if not memento:raise ValueError('archive response lacks Memento capture timestamp')
    capture=parsedate_to_datetime(memento).astimezone(timezone.utc)
    if capture.strftime('%Y%m%d%H%M%S')!=selected['timestamp']:
        raise ValueError('archive response capture differs from requested capture')
    captured_at=capture.isoformat().replace('+00:00','Z')
    current=fetch('langchain-current.json',BOARD)
    current_at=sources[-1]['retrieved_at']
    archive={'verified':True,'captured_at':captured_at,'url':old.url,'payload_sha256':sha(old.content),
             'verification':'CDX selected capture and Memento-Datetime match.'}
    jobs=job_records(old.json(),old.url,captured_at,observed,archive)
    jobs+=job_records(current.json(),BOARD,current_at,current_at)
    comparison=compare_boards(old.json(),current.json(),captured_at,current_at)
    if validate_records(records+jobs):raise ValueError('invalid extension record')
    for name,value in [('articles.json',articles),('hiring-comparison.json',comparison)]:
        (out/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    for name,items in [('public-voice-records.jsonl',records),('job-observations.jsonl',jobs)]:
        (out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in items))
    manifest={'observed_at':observed,'observed_at_basis':'UTC collection start; individual response retrieval times retained in sources.',
        'cohort_sha256':sha((out/'cohort.json').read_bytes()),
        'study_window':{'start':'2025-11-01','end':'2026-11-21'},
        'sources':sources,'public_voice_documents':len(articles),'public_voice_association_records':len(records),
        'job_observations':len(jobs),'archive_capture':archive,
        'output_sha256':{name:sha((out/name).read_bytes()) for name in ['articles.json','hiring-comparison.json','public-voice-records.jsonl','job-observations.jsonl']},
        'scope':'Evidence extension; earlier frozen experiments and labels are unchanged.',
        'limits':['One company and two job-board time points; no complete weekly job history.',
            'Date-only article publications are explicitly marked; midnight is normalization only.',
            'Multiple company passages from one article share one documentary origin.',
            'No personal independent annotation or participant measurements generated.']}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'public_voice_documents':len(articles),'job_observations':len(jobs),
                      'baseline':comparison['baseline_listed_postings'],'latest':comparison['latest_listed_postings'],
                      'net_change':comparison['net_posting_change']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['collect','replay'],nargs='?',default='collect')
    parser.add_argument('--out',type=Path,default=Path('evaluation/sueda-evidence-extension'))
    args=parser.parse_args()
    print(json.dumps(replay(args.out),indent=2)) if args.action=='replay' else collect(args.out)
