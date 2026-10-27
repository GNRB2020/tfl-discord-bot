"""Keep the login/scorer structure and application API routes intact.

Catches regressions that previously put scorer and login on the same page.
"""
import unittest
from html.parser import HTMLParser
from pathlib import Path
from aiohttp import web
from stingrays_v2.api import register_stingrays_v2

ROOT=Path(__file__).resolve().parents[1]

class IdentifierParser(HTMLParser):
    def __init__(self):
        super().__init__();self.ids=[];self.tags=[]
    def handle_starttag(self,tag,attrs):
        attr=dict(attrs)
        if 'id' in attr:self.ids.append(attr['id'])
        self.tags.append((tag,attr))

class WebContractTests(unittest.TestCase):
    def test_all_required_page_sections_are_unique(self):
        p=IdentifierParser();p.feed((ROOT/'stingrays_v2/index.html').read_text())
        for name in ['login','scorer','dashboard','competitions','admin','statistics','members','training']:
            self.assertEqual(p.ids.count(name),1, 'Duplicate or missing page section '+name)
        self.assertEqual(len(p.ids),len(set(p.ids)), 'Every HTML id must be unique')
        scorer=next(attrs for tag,attrs in p.tags if attrs.get('id')=='scorer')
        self.assertIn('hidden',scorer, 'Scorer must be hidden before authentication')

    def test_api_routes_are_unique_and_complete(self):
        app=web.Application()
        register_stingrays_v2(app)
        routes=[(r.method,r.resource.canonical) for r in app.router.routes()]
        self.assertEqual(len(routes),len(set(routes)),'Duplicate routes create undefined handler selection')
        for route in [('GET','/dart/v2/api/admin/diagnostics'),
                      ('POST','/dart/v2/api/competitions/{cid}/advance-now'),
                      ('POST','/dart/v2/api/phases/{pid}/bracket-release'),
                      ('POST','/dart/v2/api/matches/{mid}/throw'),
                      ('POST','/dart/v2/api/matches/{mid}/abort')]:
            self.assertIn(route,routes)

if __name__=='__main__':unittest.main()
