"""Fetch an official-domain archive response with scripts disabled; verify its clock."""
import argparse
import base64
from datetime import timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from collectors.browser_snapshot import ROOT, validate_url
from collectors.records import utc_now


def validate_capture(timestamp,headers,response_url):
    normalized={k.lower():v for k,v in headers.items()}
    clock=parsedate_to_datetime(normalized.get('memento-datetime',''))
    if clock.tzinfo is None:raise ValueError('Archive clock timezone required')
    clock=clock.astimezone(timezone.utc)
    if clock.strftime('%Y%m%d%H%M%S')!=timestamp:raise ValueError('Archive timestamp differs from requested CDX capture')
    if urlsplit(response_url).scheme!='https' or urlsplit(response_url).hostname!='web.archive.org' or not re.match(r'^/web/'+timestamp+r'(?:id_)?/',urlsplit(response_url).path):
        raise ValueError('Response is not the requested archive capture')
    return clock.isoformat().replace('+00:00','Z')


def capture(company_id,original_url,timestamp,out,timeout=25):
    if not re.fullmatch(r'\d{14}',timestamp):raise ValueError('Exact CDX timestamp required')
    company=next(c for c in json.loads((ROOT/'data/registry/cohort.json').read_text())['companies'] if c['company_id']==company_id)
    validate_url(original_url,company['domain'])
    if out.exists():raise ValueError('Refusing to overwrite an archive retrieval')
    from selenium import webdriver
    options=webdriver.ChromeOptions();options.add_argument('--headless=new');options.add_argument('--incognito')
    options.add_experimental_option('prefs',{'profile.managed_default_content_settings.javascript':2})
    options.set_capability('goog:loggingPrefs',{'performance':'ALL'})
    driver=webdriver.Chrome(options=options);url='https://web.archive.org/web/'+timestamp+'id_/'+original_url
    result={'company_id':company_id,'original_url':original_url,'requested_url':url,'timestamp':timestamp,
            'method':'selenium_network_response_body_scripts_disabled','scripts_disabled':True,'observed_at':utc_now(),
            'body_basis':'CDP response body, not rendered DOM; UTF-8 text or decoded base64 as supplied by Chrome.',
            'status':'retrieval_unavailable'}
    out.mkdir(parents=True)
    try:
        driver.set_page_load_timeout(timeout);driver.execute_cdp_cmd('Network.enable',{});driver.get(url)
        events=[json.loads(x['message'])['message'] for x in driver.get_log('performance')]
        documents=[e['params'] for e in events if e['method']=='Network.responseReceived' and e['params'].get('type')=='Document' and e['params']['response']['url'].startswith('https://web.archive.org/web/')]
        if not documents:raise ValueError('No archived main-document response captured')
        item=documents[-1];response=item['response'];headers=dict(response['headers'])
        for e in events:
            if e['method']=='Network.responseReceivedExtraInfo' and e['params']['requestId']==item['requestId']:headers.update(e['params']['headers'])
        if response['status']!=200:raise ValueError('Archive response is not HTTP 200')
        snapshot_at=validate_capture(timestamp,headers,response['url'])
        if response['url']!=url:raise ValueError('Archived document URL redirected; use its independently discovered CDX URL')
        body=driver.execute_cdp_cmd('Network.getResponseBody',{'requestId':item['requestId']})
        payload=base64.b64decode(body['body']) if body.get('base64Encoded') else body['body'].encode('utf-8')
        (out/'response.html').write_bytes(payload)
        result.update(status='archive_clock_verified',response_url=response['url'],snapshot_at=snapshot_at,
            memento_datetime=next(v for k,v in headers.items() if k.lower()=='memento-datetime'),
            file='response.html',sha256=hashlib.sha256(payload).hexdigest(),browser_version=driver.capabilities.get('browserVersion'))
    except Exception as exc:
        result['error_type']=type(exc).__name__;result['error']=str(exc).splitlines()[0][:450]
    finally:
        driver.quit();(out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--company',required=True);p.add_argument('--original-url',required=True);p.add_argument('--timestamp',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    print(json.dumps(capture(a.company,a.original_url,a.timestamp,a.out),indent=2))


if __name__=='__main__':main()
