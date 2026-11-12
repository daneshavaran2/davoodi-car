"""Offline regressions for users who type or say just the car name."""
import os
os.environ.setdefault('ADMIN_PASSWORD','offline-v28-password')
os.environ.setdefault('SESSION_SECRET','offline-v28-session-secret-longer-than-thirty-two')
os.environ.setdefault('DB_PATH','/tmp/davoodi-v28-test.sqlite3')
import unittest
from unittest.mock import patch
import main
from model_overview import model_overview,name_only_search


def row(year,trim,price,condition='کارکرده',suffix='1'):
    return {'url':'https://bama.ir/car/detail-'+suffix,
        'domain':'bama.ir','title':'فیدلیتی '+trim+' '+str(year),
        'year':year,'trim':trim,'price':price,'kind':'listing',
        'is_new':condition=='صفر','mileage':0 if condition=='صفر' else 50000,
        'accepted':True}


class ModelOnlyV28(unittest.TestCase):
    def test_fidelity_name_only_does_not_demand_trim(self):
        vehicle=main.resolve_search_vehicle(main.Search(query='فیدلیتی'))
        self.assertEqual(vehicle['model'],'فیدلیتی')
        self.assertIsNone(vehicle['trim'])
        self.assertIsNone(vehicle['year'])
        self.assertIsNone(vehicle['mileage'])
        self.assertTrue(name_only_search(vehicle))

    def test_different_years_and_trims_are_not_combined(self):
        rows=[row(1402,'پرایم',2_000_000_000,suffix='1'),
              row(1403,'پرایم',3_000_000_000,suffix='2'),
              row(1403,'پرستیژ',4_000_000_000,suffix='3'),
              row(1403,'پرستیژ',4_300_000_000,suffix='4')]
        d=model_overview({'model':'فیدلیتی'},rows)
        self.assertEqual(d['listing_count'],4)
        self.assertEqual(d['groups_total'],3)
        self.assertTrue(any(g['trim']=='پرستیژ' and g['price_min']==4_000_000_000 and g['price_max']==4_300_000_000 for g in d['groups']))
        self.assertTrue(all(g['price_min']<=g['price_max'] for g in d['groups']))

    def test_zero_and_used_cars_separate(self):
        data=model_overview({'model':'فیدلیتی'},
          [row(1403,'پرایم',3_100_000_000,'صفر','10'),row(1403,'پرایم',2_600_000_000,'کارکرده','11')])
        self.assertEqual(data['groups_total'],2)
        self.assertEqual({x['condition'] for x in data['groups']},{'صفر','کارکرده'})

    def test_unverified_and_reference_only_prices_are_not_shown(self):
        items=[{**row(1403,'پرایم',8_000_000_000,suffix='21'),'accepted':False},
               {**row(1403,'پرایم',6_000_000_000,suffix='22'),'kind':'market_price'}]
        self.assertEqual(model_overview({'model':'فیدلیتی'},items)['groups'],[])

    def test_precise_search_keeps_existing_price_path(self):
        self.assertFalse(name_only_search({'model':'سانتافه','year':2025,'mileage':0,'trim':None}))
        self.assertTrue(name_only_search({'model':'سانتافه','year':2025,'mileage':None,'trim':None}))

    def test_live_search_wrapper_never_invents_price_without_ads(self):
        car=main.resolve_search_vehicle(main.Search(query='فیدلیتی'))
        with patch.object(main,'AVALAI_KEY',''),patch.object(main,'OPENAI_KEY',''),\
             patch.object(main,'_direct_connector',return_value=None),\
             patch.object(main,'_builtin_connector',return_value=[]):
            d=main.research_market(car)
        self.assertIsNotNone(d['model_overview'])
        self.assertEqual(d['model_overview']['groups'],[])
        self.assertIsNone(d['new']['price_average'])
        self.assertIsNone(d['used']['price_average'])


if __name__=='__main__':
    unittest.main(verbosity=2)
