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
