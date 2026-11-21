"""Optional isolated Selenium capture of a CURRENT public company page.

Rendered output is a discovery artifact, not a verified complete job board.
Never use this command to reconstruct historical stock from archive pages.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from collectors.records import utc_now

ROOT=Path(__file__).resolve().parents[1]


def validate_url(url,domain):
    u=urlsplit(url)
    if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or not (u.hostname==domain or (u.hostname or '').endswith('.'+domain)):
        raise ValueError('A current HTTPS page on the selected official company domain is required.')


def capture(company_id,url,selector,out,timeout=25,driver_path=None,browser_binary=None):
    cohort=json.loads((ROOT/'data/registry/cohort.json').read_text())
    company=next(c for c in cohort['companies'] if c['company_id']==company_id)
    validate_url(url,company['domain'])
    if out.exists():raise ValueError('Refusing to overwrite a browser observation directory.')
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:
        raise RuntimeError('Install optional browser dependencies: pip install -r requirements-browser.txt') from exc
    options=webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--incognito')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1440,1000')
    if browser_binary:options.binary_location=browser_binary
    driver=webdriver.Chrome(service=Service(executable_path=driver_path) if driver_path else Service(),options=options)
    try:
        driver.set_page_load_timeout(timeout);driver.get(url)
        validate_url(driver.current_url,company['domain'])
        # The selector must be supplied for this site. Mere document.readyState
        # does not prove a JS-populated list is present or complete.
        WebDriverWait(driver,timeout).until(lambda d:any(e.is_displayed() for e in d.find_elements(By.CSS_SELECTOR,selector)))
        observed=utc_now();html=driver.page_source;final_url=driver.current_url
        validate_url(final_url,company['domain'])
        out.mkdir(parents=True)
        (out/'rendered.html').write_text(html)
        manifest=dict(company_id=company_id,requested_url=url,response_url=final_url,observed_at=observed,
            source_snapshot_at=observed,source_clock='Current browser observation only; not an event or publication date.',
            method='selenium_current_render',readiness_selector=selector,
            matched_elements=len(driver.find_elements(By.CSS_SELECTOR,selector)),
            browser_version=driver.capabilities.get('browserVersion'),
            webdriver_version=driver.capabilities.get('chrome',{}).get('chromedriverVersion'),
            sha256=hashlib.sha256((out/'rendered.html').read_bytes()).hexdigest(),
            verified_complete_board=False,
            limits=['Selector presence is not proof of board completeness; a reviewed site parser is required.',
                    'Iframe content is not included in the parent DOM; parse its official API or capture it separately.',
                    'Browser observation time cannot establish historical posting stock or participant decisions.'])
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        return manifest
    finally:driver.quit()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--company',required=True);p.add_argument('--url',required=True)
    p.add_argument('--selector',required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--timeout',type=int,default=25);p.add_argument('--driver-path');p.add_argument('--browser-binary')
    a=p.parse_args()
    print(json.dumps(capture(a.company,a.url,a.selector,a.out,a.timeout,a.driver_path,a.browser_binary),indent=2))


if __name__=='__main__':main()
