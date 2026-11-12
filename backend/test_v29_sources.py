"""Offline regression tests for v29 source coverage, matching and concise quotes."""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('ADMIN_PASSWORD','v29-test-only-password')
os.environ.setdefault('SESSION_SECRET','v29-test-only-secret-at-least-thirty-two-characters')
os.environ.setdefault('DB_PATH','/tmp/davoodi-test-v29.sqlite')

import main
from source_health import record_source_results, read_source_results
from model_overview import model_overview


def _factory(path):
    def db():
        c=sqlite3.connect(path)
        c.row_factory=sqlite3.Row
        return c
    return db


class SourceAndPriceV29Tests(unittest.TestCase):
    def test_source_attempts_error_and_last_verified_are_persistent(self):
        with tempfile.TemporaryDirectory() as folder:
            db=_factory(folder+'/source-health.db')
            first=record_source_results(db,[
              {'name':'باما','domain':'bama.ir','status':'evidence','attempted':True,
               'accepted_count':2,'raw_count':5,'modes':['builtin_playwright']},
              {'name':'شیپور','domain':'sheypoor.com','status':'not_configured',
               'attempted':False,'accepted_count':0,'raw_count':0,'modes':[]},
            ],now=1700000000)
            self.assertEqual(first[0]['last_verified_price_at'],1700000000)
            self.assertEqual(first[0]['checked_at'],1700000000)
            self.assertIsNone(first[1]['checked_at'])
            self.assertIsNone(first[1]['last_attempt_at'])
            second=record_source_results(db,[
              {'name':'باما','domain':'bama.ir','status':'rate_limited',
               'attempted':True,'accepted_count':0,'raw_count':0,
               'detail':'429 محدودیت','modes':['builtin_playwright']},
              {'name':'شیپور','domain':'sheypoor.com','status':'not_configured',
               'attempted':False,'accepted_count':0,'raw_count':0,'modes':[]},
            ],now=1700000300)
            self.assertEqual(second[0]['last_verified_price_at'],1700000000)
            self.assertEqual(second[0]['last_attempt_at'],1700000300)
            self.assertEqual(second[0]['last_error_at'],1700000300)
            self.assertIsNone(second[1]['last_attempt_at'])
            stored={x['domain']:x for x in read_source_results(db)}
            self.assertEqual(stored['bama.ir']['status'],'rate_limited')
            self.assertEqual(stored['bama.ir']['last_verified_price_at'],1700000000)
            self.assertEqual(stored['sheypoor.com']['status'],'not_configured')

    def test_title_year_conflicts_with_structured_year(self):
        vehicle={'brand':'بهمن موتور','model':'فیدلیتی','year':None,
                 'trim':None,'mileage':None}
        source={'name':'باما','domain':'bama.ir'}
        row={'url':'https://bama.ir/car/detail-8888','kind':'listing',
             'title':'فیدلیتی پرایم مدل ۱۴۰۳','year':1402,'price':2600000000,
             'mileage':50000,'is_new':False}
        result=main._normalize_result(source,row,vehicle)
        self.assertFalse(result['accepted'])
        self.assertIn('سال',result['rejection_reason'])

    def test_title_trim_conflicts_with_structured_trim(self):
        vehicle={'brand':'بهمن موتور','model':'فیدلیتی','year':None,
                 'trim':None,'mileage':None}
        source={'name':'باما','domain':'bama.ir'}
        row={'url':'https://bama.ir/car/detail-8888','kind':'listing',
             'title':'فیدلیتی پرایم ۱۴۰۳','year':1403,'trim':'پرستیژ',
             'price':2600000000,'mileage':50000,'is_new':False}
        result=main._normalize_result(source,row,vehicle)
        self.assertFalse(result['accepted'])
        self.assertIn('تیپ',result['rejection_reason'])

    def test_english_prime_alias_is_grouped_as_persian_prime(self):
        vehicle={'brand':'بهمن موتور','model':'فیدلیتی','year':None,
                 'trim':None,'mileage':None}
        source={'name':'باما','domain':'bama.ir'}
        row={'url':'https://bama.ir/car/detail-8888','kind':'listing',
             'title':'فیدلیتی پرایم مدل ۱۴۰۳','year':1403,'trim':'Prime',
             'price':2600000000,'mileage':50000,'is_new':False}
        result=main._normalize_result(source,row,vehicle)
        self.assertIsNone(result['rejection_reason'])
        self.assertEqual(result['trim'],'پرایم')

    def test_missing_new_used_status_never_becomes_used(self):
        rows=[{'accepted':True,'url':'https://bama.ir/car/detail-1',
              'domain':'bama.ir','source':'باما','price':2000000000,
              'year':1403,'trim':'پرایم','is_new':None,'mileage':None,
              'kind':'listing'},
             {'accepted':True,'url':'https://divar.ir/v/abcd1234',
              'domain':'divar.ir','source':'دیوار','price':2100000000,
              'year':1403,'trim':'پرایم','is_new':False,'mileage':50000,
              'kind':'listing'}]
        overview=model_overview({'model':'فیدلیتی'},rows)
        self.assertEqual(overview['groups_total'],2)
        self.assertEqual({x['condition'] for x in overview['groups']},
                         {'وضعیت نامشخص','کارکرده'})

    def test_contradictory_zero_used_metadata_is_never_priced(self):
        from market_intelligence import score_evidence
        item={'accepted':True,'url':'https://bama.ir/car/detail-999',
              'domain':'bama.ir','price':2600000000,'kind':'listing',
              'title':'فیدلیتی پرایم ۱۴۰۳','year':1403,'trim':'پرایم',
              'is_new':False,'mileage':0}
        score,reason=score_evidence(item,{'model':'فیدلیتی'})
        self.assertEqual(score,0)
        self.assertIn('متناقض',reason)
        self.assertEqual(model_overview({'model':'فیدلیتی'},[item])['groups'],[])

    def test_links_include_real_source_name_and_are_unique(self):
        rows=[{'accepted':True,'url':url,'source':source,'domain':domain,
              'price':price,'kind':'listing','year':1403,'trim':'پرایم',
              'is_new':False,'mileage':50000} for (url,source,domain,price) in [
                 ('https://bama.ir/car/detail-111','باما','bama.ir',2000000000),
                 ('https://bama.ir/car/detail-222','باما','bama.ir',2010000000),
                 ('https://divar.ir/v/aaaabbbb','دیوار','divar.ir',2020000000)]]
        group=model_overview({'model':'فیدلیتی'},rows)['groups'][0]
        self.assertEqual(group['source_count'],2)
        self.assertEqual(group['ads'][0]['source'],'باما')
        self.assertEqual(group['ads'][1]['source'],'دیوار')
        self.assertEqual(len(group['links']),3)
        self.assertEqual(len(set(group['links'])),3)

    def test_unsupported_sites_are_not_reported_as_checked(self):
        car=main.resolve_search_vehicle(main.Search(query='فیدلیتی'))
        def built_in(source,vehicle):
            return None if source['domain'] in ('sheypoor.com','karnameh.com') else []
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(main,'DB_PATH',folder+'/audit.db'),\
                 patch.object(main,'AVALAI_KEY',''),\
                 patch.object(main,'OPENAI_KEY',''),\
                 patch.object(main,'_direct_connector',return_value=None),\
                 patch.object(main,'_builtin_connector',side_effect=built_in):
                result=main.research_market(car)
        statuses={x['domain']:x for x in result['site_status']}
        for domain in ('sheypoor.com','karnameh.com'):
            self.assertEqual(statuses[domain]['status'],'not_configured')
            self.assertFalse(statuses[domain]['attempted'])
            self.assertIsNone(statuses[domain]['checked_at'])
        self.assertEqual(result['model_overview']['groups'],[])
        self.assertEqual(result['diagnostics']['accepted'],0)


if __name__=='__main__':
    unittest.main(verbosity=2)
