"""Fetch retained CDX entries for one exact board landing URL into a new manifest."""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
import requests


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--discovery',type=Path,required=True)
    p.add_argument('--company',required=True)
    p.add_argument('--board-url',required=True)
    a=p.parse_args();output=a.out/(a.company+'-captures.json')
    if output.exists():raise SystemExit('Refusing to overwrite retained captures')
    expected=urlsplit(a.board_url)
    if expected.scheme!='https' or expected.hostname not in {'jobs.ashbyhq.com','job-boards.greenhouse.io'} or expected.query:
        raise SystemExit('Exact public board landing URL required')
    sources=json.loads(a.discovery.read_text());captures=[]
    for source in sources:
        if source.get('company_id')!=a.company:continue
        for c in source.get('captures',[]):
            u=urlsplit(c['original'])
            if u.hostname==expected.hostname and u.path.rstrip('/')==expected.path.rstrip('/') and not u.query:
                captures.append(c)
    (a.out/'sources').mkdir(parents=True,exist_ok=True);results=[]
    for c in captures[-2:]:
        ts=c['timestamp'];url='https://web.archive.org/web/'+ts+'id_/'+c['original']
        d={'company_id':a.company,'timestamp':ts,'original_url':c['original'],'requested_url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
        try:
            r=requests.get(url,timeout=25,headers={'User-Agent':'TrendScout-research/1.0'});r.raise_for_status()
            when=parsedate_to_datetime(r.headers['Memento-Datetime']).astimezone(timezone.utc)
            name='sources/'+a.company+'-'+ts+'.html';f=a.out/name
            if f.exists():raise ValueError('Retained source already exists')
            f.write_bytes(r.content)
            d.update(http_status=r.status_code,response_url=r.url,file=name,sha256=hashlib.sha256(r.content).hexdigest(),
                     memento_datetime=r.headers['Memento-Datetime'],capture_verified=when.strftime('%Y%m%d%H%M%S')==ts,
                     snapshot_at=when.isoformat().replace('+00:00','Z'))
        except (requests.RequestException,ValueError,KeyError) as e:d['error']=type(e).__name__
        results.append(d)
    output.write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':main()
