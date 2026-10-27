"""Headless offline smoke test for login, modal safety and admin navigation.

No production database or authentication credentials are used.
"""
from pathlib import Path
import os
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]/'stingrays_v2'

def run():
    with sync_playwright() as p:
        opts={'headless':True,'args':['--no-sandbox']}
        binary=os.environ.get('CHROMIUM_PATH')
        if binary:opts['executable_path']=binary
        browser=p.chromium.launch(**opts)
        try:
            for width in (1366,390):
                page=browser.new_page(viewport={'width':width,'height':800})
                errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('about:blank')
                page.set_content((ROOT/'index.html').read_text(encoding='utf8'),wait_until='domcontentloaded')
                page.add_style_tag(content=(ROOT/'style.css').read_text(encoding='utf8'))
                page.add_script_tag(content=(ROOT/'training_minigames.js').read_text(encoding='utf8'))
                page.add_script_tag(content=(ROOT/'app.js').read_text(encoding='utf8'))
                page.wait_for_timeout(100)
                assert page.locator('#login').is_visible(),f'Login hidden at {width}'
                assert not page.locator('#scorer').is_visible(),f'Scorer visible before login at {width}'
                page.locator('#forgotPassword').click()
                assert page.locator('.config-sheet').is_visible()
                page.locator('.config-sheet input').fill('StingrayTester')
                page.locator('.sheet-shade').click(position={'x':2,'y':2},force=True)
                assert page.locator('.config-sheet').is_visible(), 'Backdrop must not close popup'
                assert page.locator('.config-sheet input').input_value()=='StingrayTester'
                page.keyboard.press('Escape')
                assert page.locator('.config-sheet').is_visible(), 'Escape must not close popup'
                page.locator('.sheet-actions button').first.click()
                assert page.locator('.config-sheet').count()==0, 'Explicit cancel should close popup'
                assert page.locator('.v2-admin-nav button').count()>=8
                page.locator('#admin').evaluate('(e)=>e.hidden=false')
                page.locator('#v2-admin-tab-diagnostics').click(force=True)
                assert page.locator('#v2-admin-pane-diagnostics').is_visible(), 'Admin diagnostics tab inaccessible'
                assert not errors,f'Browser JS errors at {width}: {errors}'
                page.close()
        finally:
            browser.close()

if __name__=='__main__':run();print('Stingray browser smoke passed: desktop and mobile')
