from decimal import Decimal
from datetime import date
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from production.models import (
    Factory, Size, Grade, Glaze, TechnicalType, Profile,
    Production, ProductionImportBatch, ProductionImportRow
)
from production.management_reporting import get_management_report_data
from production.forms import ImportRowEditForm, FilterForm


class RecordTypeFeatureTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = get_user_model().objects.create_superuser('admin_rec', 'admin@example.test', 'Pass-12345-Admin!')
        Profile.objects.create(user=self.admin, role='admin')
        self.client.force_login(self.admin)

        self.sadaf = Factory.objects.create(name='صدف', active=True)
        self.mahtab = Factory.objects.create(name='مهتاب', active=True)

        self.size_40_120 = Size.objects.create(width=40, length=120, active=True)
        self.size_60_60 = Size.objects.create(width=60, length=60, active=True)
        self.size_30_100 = Size.objects.create(width=30, length=100, active=True)

        self.grade_1 = Grade.objects.create(name='درجه 1', rank=1, color='#159b9a', active=True)
        self.grade_2 = Grade.objects.create(name='درجه 2', rank=2, color='#eab308', active=True)

        self.glaze = Glaze.objects.create(name='نانو پولیش', active=True)
        self.tech = TechnicalType.objects.create(name='10 میلی‌متر')

    def test_model_defaults_and_choices(self):
        """Production record defaults to 'production' and can be set to 'inventory'."""
        prod = Production.objects.create(
            factory=self.sadaf,
            date=date(2026, 10, 19),
            size=self.size_40_120,
            grade=self.grade_1,
            area=Decimal('3024.00'),
            created_by=self.admin
        )
        self.assertEqual(prod.record_type, 'production')
        self.assertEqual(prod.get_record_type_display(), 'تولید واقعی')
        snap = prod.snapshot()
        self.assertEqual(snap.get('نوع رکورد'), 'تولید واقعی')

        inv = Production.objects.create(
            factory=self.sadaf,
            date=date(2026, 10, 19),
            record_type='inventory',
            size=self.size_30_100,
            grade=self.grade_1,
            area=Decimal('2370.00'),
            created_by=self.admin
        )
        self.assertEqual(inv.record_type, 'inventory')
        self.assertEqual(inv.get_record_type_display(), 'موجودی انبار')

    def test_import_row_edit_form(self):
        """ImportRowEditForm supports record_type."""
        form = ImportRowEditForm(data={
            'row_id': 1,
            'record_type': 'inventory',
            'size': self.size_30_100.pk,
            'grade': self.grade_1.pk,
            'area': '2370.00',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['record_type'], 'inventory')

    def test_user_exact_scenario_calculations(self):
        """
        User's exact scenario:
        Actual production:
          - Size 40x120 = 3024 m2 (Grade 1)
          - Size 60x60 = 2186 m2 (Grade 2)
        Inventory:
          - Size 30x100 = 2370 m2 (Grade 1)

        Total actual production must be exactly 5210 m2.
        Inventory 2370 m2 must be independent and not affect actual production totals or grade percentages.
        """
        d = date(2026, 10, 19)
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='production',
            size=self.size_40_120, grade=self.grade_1, area=Decimal('3024.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='production',
            size=self.size_60_60, grade=self.grade_2, area=Decimal('2186.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_30_100, grade=self.grade_1, area=Decimal('2370.00'), created_by=self.admin
        )

        cleaned_data = {'start': d, 'end': d, 'factory': [self.sadaf]}
        report = get_management_report_data(self.admin, cleaned_data, {}, include_days=True)

        summary = report['summary_cards']
        self.assertEqual(summary['total_area'], Decimal('5210.00'))
        self.assertEqual(summary['inventory_total_area'], Decimal('2370.00'))
        self.assertEqual(summary['first_grade_area'], Decimal('3024.00'))
        # Grade 1 percentage: 3024 / 5210 * 100 = 58.04%
        expected_pct = (Decimal('3024.00') / Decimal('5210.00') * 100).quantize(Decimal('0.01'))
        self.assertEqual(summary['first_grade_percentage'].quantize(Decimal('0.01')), expected_pct)

        # Daily report
        daily = report['daily_reports'][0]['report']
        sadaf_table = daily['factory_tables'][0]
        self.assertEqual(sadaf_table['total_area'], Decimal('5210.00'))
        self.assertEqual(sadaf_table['inventory_total_area'], Decimal('2370.00'))
        self.assertTrue(sadaf_table['has_production'])
        self.assertTrue(sadaf_table['has_inventory'])
        self.assertEqual(len(sadaf_table['production_rows']), 2)
        self.assertEqual(len(sadaf_table['inventory_rows']), 1)
        self.assertEqual(sadaf_table['inventory_rows'][0]['size'], self.size_30_100)
        self.assertEqual(sadaf_table['inventory_rows'][0]['total_area'], Decimal('2370.00'))

    def test_management_preview_view_rendering(self):
        """Verify the management preview page renders separated production and inventory sections."""
        d = date(2026, 10, 19)
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='production',
            size=self.size_40_120, grade=self.grade_1, area=Decimal('3024.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_30_100, grade=self.grade_1, area=Decimal('2370.00'), created_by=self.admin
        )

        from production.dates import jalali
        url = reverse('management_report') + f"?start={jalali(d)}&end={jalali(d)}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('بخش تولید واقعی', content)
        self.assertIn('بخش موجودی انبار', content)
        self.assertIn('جمع موجودی انبار', content)

    def test_multi_day_inventory_deduplication(self):
        """
        Verify multi-day range report does not double count inventory snapshots.
        If inventory is reported on Day 1 (2370) and Day 2 (2370), the range total
        for that inventory item is 2370, not 4740.
        """
        d1 = date(2026, 10, 18)
        d2 = date(2026, 10, 19)

        # Day 1
        Production.objects.create(
            factory=self.sadaf, date=d1, record_type='production',
            size=self.size_40_120, grade=self.grade_1, area=Decimal('3000.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d1, record_type='inventory',
            size=self.size_30_100, grade=self.grade_1, area=Decimal('2370.00'), created_by=self.admin
        )

        # Day 2
        Production.objects.create(
            factory=self.sadaf, date=d2, record_type='production',
            size=self.size_40_120, grade=self.grade_1, area=Decimal('2000.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d2, record_type='inventory',
            size=self.size_30_100, grade=self.grade_1, area=Decimal('2370.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d2, record_type='inventory',
            size=self.size_60_60, grade=self.grade_2, area=Decimal('1000.00'), created_by=self.admin
        )

        cleaned_data = {'start': d1, 'end': d2, 'factory': [self.sadaf]}
        report = get_management_report_data(self.admin, cleaned_data, {}, include_days=True)

        # Production sums across days: 3000 + 2000 = 5000
        self.assertEqual(report['summary_cards']['total_area'], Decimal('5000.00'))
        # Inventory takes latest snapshot per item: 2370 + 1000 = 3370 (NOT 2370 + 2370 + 1000 = 5740)
        self.assertEqual(report['summary_cards']['inventory_total_area'], Decimal('3370.00'))

    def test_grade_percentages_exact_user_example(self):
        """
        Verify the user's exact inventory example:
        Total inventory: 2369 m2
        - Grade A (Grade 1): 1703 m2 -> 71.89%
        - Ungrade (Grade 2): 539 m2 -> 22.75%
        - Grade 6 (Grade 3): 127 m2 -> 5.36%
        Sum of percentages = 100.00%

        Actual production on the same day: 3000 m2
        - Grade 1: 2000 m2 -> 66.67%
        - Grade 2: 1000 m2 -> 33.33%
        - Grade 3: 0 m2 -> 0.00%
        Sum of percentages = 100.00%

        Both actual production and inventory MUST calculate percentages using strictly
        their own independent denominators (3000 and 2369 respectively).
        """
        grade_3 = Grade.objects.create(name='درجه 6', rank=3, color='#dc2626', active=True)
        d = date(2026, 10, 19)

        # Actual Production: 3000 m2 total
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='production',
            size=self.size_40_120, grade=self.grade_1, area=Decimal('2000.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='production',
            size=self.size_40_120, grade=self.grade_2, area=Decimal('1000.00'), created_by=self.admin
        )

        # Inventory: 2369 m2 total
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_30_100, grade=self.grade_1, area=Decimal('1703.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_30_100, grade=self.grade_2, area=Decimal('539.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_30_100, grade=grade_3, area=Decimal('127.00'), created_by=self.admin
        )

        cleaned_data = {'start': d, 'end': d, 'factory': [self.sadaf]}
        report = get_management_report_data(self.admin, cleaned_data, {}, include_days=True)

        # Overall summaries
        summary = report['summary_cards']
        self.assertEqual(summary['total_area'], Decimal('3000.00'))
        self.assertEqual(summary['inventory_total_area'], Decimal('2369.00'))

        sadaf_table = report['daily_reports'][0]['report']['factory_tables'][0]

        # 1. Check Actual Production Row & Footer
        prod_row = sadaf_table['production_rows'][0]
        self.assertEqual(prod_row['total_area'], Decimal('3000.00'))
        prod_g1 = next(c for c in prod_row['grades'] if c['grade'] == self.grade_1)
        prod_g2 = next(c for c in prod_row['grades'] if c['grade'] == self.grade_2)
        prod_g3 = next(c for c in prod_row['grades'] if c['grade'] == grade_3)

        self.assertAlmostEqual(float(prod_g1['percentage']), 2000.0 / 3000.0 * 100, places=2)
        self.assertAlmostEqual(float(prod_g2['percentage']), 1000.0 / 3000.0 * 100, places=2)
        self.assertEqual(prod_g3['percentage'], Decimal('0.00'))
        prod_row_sum = (prod_g1['percentage'] + prod_g2['percentage'] + prod_g3['percentage']).quantize(Decimal('0.01'))
        self.assertEqual(prod_row_sum, Decimal('100.00'))

        prod_foot = sadaf_table['production_footer']
        foot_g1 = next(c for c in prod_foot['grades'] if c['grade'] == self.grade_1)
        foot_g2 = next(c for c in prod_foot['grades'] if c['grade'] == self.grade_2)
        self.assertAlmostEqual(float(foot_g1['percentage']), 66.67, places=2)
        self.assertAlmostEqual(float(foot_g2['percentage']), 33.33, places=2)

        # 2. Check Warehouse Inventory Row & Footer
        inv_row = sadaf_table['inventory_rows'][0]
        self.assertEqual(inv_row['total_area'], Decimal('2369.00'))
        inv_g1 = next(c for c in inv_row['grades'] if c['grade'] == self.grade_1)
        inv_g2 = next(c for c in inv_row['grades'] if c['grade'] == self.grade_2)
        inv_g3 = next(c for c in inv_row['grades'] if c['grade'] == grade_3)

        # Exact user percentages: 71.89%, 22.75%, 5.36%
        self.assertEqual(inv_g1['percentage'].quantize(Decimal('0.01')), Decimal('71.89'))
        self.assertEqual(inv_g2['percentage'].quantize(Decimal('0.01')), Decimal('22.75'))
        self.assertEqual(inv_g3['percentage'].quantize(Decimal('0.01')), Decimal('5.36'))

        inv_row_sum = (inv_g1['percentage'] + inv_g2['percentage'] + inv_g3['percentage']).quantize(Decimal('0.01'))
        self.assertEqual(inv_row_sum, Decimal('100.00'))

        # Check Inventory Footer
        inv_foot = sadaf_table['inventory_footer']
        self.assertEqual(inv_foot['total_area'], Decimal('2369.00'))
        foot_inv_g1 = next(c for c in inv_foot['grades'] if c['grade'] == self.grade_1)
        foot_inv_g2 = next(c for c in inv_foot['grades'] if c['grade'] == self.grade_2)
        foot_inv_g3 = next(c for c in inv_foot['grades'] if c['grade'] == grade_3)

        self.assertEqual(foot_inv_g1['percentage'].quantize(Decimal('0.01')), Decimal('71.89'))
        self.assertEqual(foot_inv_g2['percentage'].quantize(Decimal('0.01')), Decimal('22.75'))
        self.assertEqual(foot_inv_g3['percentage'].quantize(Decimal('0.01')), Decimal('5.36'))
        inv_foot_sum = (foot_inv_g1['percentage'] + foot_inv_g2['percentage'] + foot_inv_g3['percentage']).quantize(Decimal('0.01'))
        self.assertEqual(inv_foot_sum, Decimal('100.00'))

    def test_multi_product_inventory_grade_percentages(self):
        """
        Verify multi-product inventory calculations:
        - Product 1 row % uses Product 1 area as denominator.
        - Product 2 row % uses Product 2 area as denominator.
        - Inventory footer row uses total factory inventory area as denominator.
        """
        grade_3 = Grade.objects.create(name='درجه 6', rank=3, color='#dc2626', active=True)
        d = date(2026, 10, 19)

        # Product 1: Size 30x100 (Total = 1000 m2)
        # 700 Grade 1 (70%), 300 Grade 2 (30%)
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_30_100, grade=self.grade_1, area=Decimal('700.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_30_100, grade=self.grade_2, area=Decimal('300.00'), created_by=self.admin
        )

        # Product 2: Size 60x60 (Total = 1369 m2)
        # 1003 Grade 1 (73.27%), 239 Grade 2 (17.46%), 127 Grade 3 (9.28%)
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_60_60, grade=self.grade_1, area=Decimal('1003.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_60_60, grade=self.grade_2, area=Decimal('239.00'), created_by=self.admin
        )
        Production.objects.create(
            factory=self.sadaf, date=d, record_type='inventory',
            size=self.size_60_60, grade=grade_3, area=Decimal('127.00'), created_by=self.admin
        )

        cleaned_data = {'start': d, 'end': d, 'factory': [self.sadaf]}
        report = get_management_report_data(self.admin, cleaned_data, {}, include_days=True)
        sadaf_table = report['daily_reports'][0]['report']['factory_tables'][0]

        self.assertEqual(len(sadaf_table['inventory_rows']), 2)

        # Product 1 row checks
        r1 = next(r for r in sadaf_table['inventory_rows'] if r['size'] == self.size_30_100)
        self.assertEqual(r1['total_area'], Decimal('1000.00'))
        r1_g1 = next(c for c in r1['grades'] if c['grade'] == self.grade_1)
        r1_g2 = next(c for c in r1['grades'] if c['grade'] == self.grade_2)
        self.assertEqual(r1_g1['percentage'].quantize(Decimal('0.01')), Decimal('70.00'))
        self.assertEqual(r1_g2['percentage'].quantize(Decimal('0.01')), Decimal('30.00'))

        # Product 2 row checks
        r2 = next(r for r in sadaf_table['inventory_rows'] if r['size'] == self.size_60_60)
        self.assertEqual(r2['total_area'], Decimal('1369.00'))
        r2_g1 = next(c for c in r2['grades'] if c['grade'] == self.grade_1)
        r2_g2 = next(c for c in r2['grades'] if c['grade'] == self.grade_2)
        r2_g3 = next(c for c in r2['grades'] if c['grade'] == grade_3)
        self.assertEqual(r2_g1['percentage'].quantize(Decimal('0.01')), Decimal('73.27'))
        self.assertEqual(r2_g2['percentage'].quantize(Decimal('0.01')), Decimal('17.46'))
        self.assertEqual(r2_g3['percentage'].quantize(Decimal('0.01')), Decimal('9.28'))

        # Inventory Footer checks: Denominator = 1000 + 1369 = 2369 m2
        inv_foot = sadaf_table['inventory_footer']
        self.assertEqual(inv_foot['total_area'], Decimal('2369.00'))
        foot_g1 = next(c for c in inv_foot['grades'] if c['grade'] == self.grade_1)
        foot_g2 = next(c for c in inv_foot['grades'] if c['grade'] == self.grade_2)
        foot_g3 = next(c for c in inv_foot['grades'] if c['grade'] == grade_3)

        # Grade 1 total: 700 + 1003 = 1703 -> 71.89%
        self.assertEqual(foot_g1['percentage'].quantize(Decimal('0.01')), Decimal('71.89'))
        # Grade 2 total: 300 + 239 = 539 -> 22.75%
        self.assertEqual(foot_g2['percentage'].quantize(Decimal('0.01')), Decimal('22.75'))
        # Grade 3 total: 127 -> 5.36%
        self.assertEqual(foot_g3['percentage'].quantize(Decimal('0.01')), Decimal('5.36'))
        inv_foot_sum = (foot_g1['percentage'] + foot_g2['percentage'] + foot_g3['percentage']).quantize(Decimal('0.01'))
        self.assertEqual(inv_foot_sum, Decimal('100.00'))

