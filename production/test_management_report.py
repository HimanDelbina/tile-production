import uuid
from decimal import Decimal as D
from datetime import date, timedelta
from unittest.mock import patch
from django.test import TestCase, Client
from django.http import QueryDict
from django.contrib.auth import get_user_model
from django.utils import timezone

from production.models import (
    Factory, Size, Grade, Profile, Production,
    ProductionImportBatch, ProductionImportRow
)
from production.dates import parse_jalali, jalali, period
from production.management_reporting import get_management_report_data, is_first_grade
from production.reporting import summarize, report_table


class ManagementReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            'admin_user', 'admin@example.com', 'AdminPass123!'
        )
        cls.factory_a = Factory.objects.create(name='کارخانه الف')
        cls.factory_b = Factory.objects.create(name='کارخانه ب')
        cls.size_60_120 = Size.objects.create(width=60, length=120)

        # Grades: Grade 1, Grade 2, Ungraded
        cls.grade_1 = Grade.objects.create(name='درجه ۱', rank=1, color='#159b9a')
        cls.grade_2 = Grade.objects.create(name='درجه ۲', rank=2, color='#eba743')
        cls.grade_ungraded = Grade.objects.create(name='آنگرید', rank=3, color='#657dba')

        cls.test_date = period('yesterday')[0]

        # Factory A: Grade 1: 800, Grade 2: 200 (Total = 1000)
        Production.objects.create(
            factory=cls.factory_a, size=cls.size_60_120, grade=cls.grade_1,
            area=D('800.00'), date=cls.test_date, created_by=cls.admin
        )
        Production.objects.create(
            factory=cls.factory_a, size=cls.size_60_120, grade=cls.grade_2,
            area=D('200.00'), date=cls.test_date, created_by=cls.admin
        )

        # Factory B: Grade 1: 100, Ungraded: 400 (Total = 500)
        Production.objects.create(
            factory=cls.factory_b, size=cls.size_60_120, grade=cls.grade_1,
            area=D('100.00'), date=cls.test_date, created_by=cls.admin
        )
        Production.objects.create(
            factory=cls.factory_b, size=cls.size_60_120, grade=cls.grade_ungraded,
            area=D('400.00'), date=cls.test_date, created_by=cls.admin
        )

        # Viewer with access only to Factory A
        cls.viewer_a = get_user_model().objects.create_user(
            'viewer_a', 'viewer_a@example.com', 'ViewerPass123!'
        )
        p = Profile.objects.create(user=cls.viewer_a, role='viewer')
        p.factories.add(cls.factory_a)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_preview_matches_original_report_and_preserves_filters(self):
        params = {'start': jalali(self.test_date), 'end': jalali(self.test_date), 'factory': self.factory_a.pk}
        original = self.client.get('/', params)
        preview = self.client.get('/management-preview/', params)
        self.assertTemplateUsed(original, 'production/management_preview.html')
        self.assertTemplateUsed(preview, 'production/management_report.html')
        self.assertEqual(preview.context['report']['summary_cards'], original.context['report']['summary_cards'])
        self.assertEqual(preview.context['active_summary'], original.context['active_summary'])
        self.assertContains(original, 'تولید در یک نگاه')
        self.assertContains(original, '۱٬۰۰۰')
        self.assertNotContains(original, '۱٬۰۰۰٫۰۰')
        self.assertNotContains(original, 'کارخانه ب</a>')

    def test_preview_requires_login_and_limits_factory_access(self):
        self.client.logout()
        response = self.client.get('/')
        self.assertRedirects(response, '/login/?next=/', fetch_redirect_response=False)
        self.client.force_login(self.viewer_a)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['report']['summary_cards']['total_area'], D('1000.00'))
        self.assertNotContains(response, 'کارخانه ب')
        response = self.client.get('/', {'factory': self.factory_b.pk})
        self.assertEqual(response.status_code, 400)

    def test_preview_empty_and_invalid_dates(self):
        response = self.client.get('/', {'start': '1400/01/01', 'end': '1400/01/01'})
        self.assertContains(response, 'تولیدی ثبت نشده است')
        self.assertContains(response, '۱۴۰۰/۰۱/۰۱')
        self.assertIsNone(response.context['report']['summary_cards']['first_grade_percentage'])
        response = self.client.get('/', {'start': '1405/06/20', 'end': '1405/06/10'})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'پایان بازه نباید قبل از شروع تاریخ باشد', status_code=400)

    def test_preview_samples_do_not_change_real_records(self):
        before = list(Production.objects.order_by('pk').values())
        original = self.client.get('/management-preview/')
        response = self.client.get('/', {'preset': 'yesterday', 'demo': '1'})
        self.assertContains(response, 'دادهٔ نمونه')
        self.assertGreater(response.context['report']['summary_cards']['total_area'], 0)
        self.assertEqual(list(Production.objects.order_by('pk').values()), before)
        real_report = self.client.get('/management-preview/', {'demo': '1'})
        self.assertEqual(real_report.context['report']['summary_cards']['total_area'], original.context['report']['summary_cards']['total_area'])
        self.assertNotContains(real_report, 'دادهٔ نمونه')

    def test_preview_samples_respect_dates_and_permissions(self):
        self.client.force_login(self.viewer_a)
        response = self.client.get('/', {'preset': 'yesterday', 'demo': '1'})
        self.assertNotContains(response, 'کارخانه ب')
        response = self.client.get('/', {'preset': 'today', 'demo': '1'})
        self.assertEqual(response.context['report']['summary_cards']['total_area'], D('0'))
        self.assertContains(response, 'تولیدی ثبت نشده است')

    @patch('production.dates.timezone.localdate', return_value=date(2026, 9, 15))
    def test_preview_sample_days_sum_in_date_range(self, _today):
        before = list(Production.objects.order_by('pk').values())
        day_22 = self.client.get('/', {'demo': '1', 'start': '1405/06/22', 'end': '1405/06/22'})
        day_23 = self.client.get('/', {'demo': '1', 'start': '1405/06/23', 'end': '1405/06/23'})
        combined = self.client.get('/', {'demo': '1', 'start': '1405/06/22', 'end': '1405/06/23'})
        total_22 = day_22.context['report']['summary_cards']['total_area']
        total_23 = day_23.context['report']['summary_cards']['total_area']
        self.assertGreater(total_22, 0)
        self.assertNotEqual(total_22, total_23)
        self.assertEqual(combined.context['report']['summary_cards']['total_area'], total_22 + total_23)
        days = combined.context['report']['daily_reports']
        self.assertEqual([day['date'] for day in days], [parse_jalali('1405/06/22'), parse_jalali('1405/06/23')])
        self.assertEqual([day['report']['summary_cards']['total_area'] for day in days], [total_22, total_23])
        self.assertContains(combined, 'تولید روز ۱۴۰۵/۰۶/۲۲')
        self.assertContains(combined, 'تولید روز ۱۴۰۵/۰۶/۲۳')
        self.assertEqual(list(Production.objects.order_by('pk').values()), before)

    def test_daily_real_report_and_links_respect_day_and_access(self):
        from urllib.parse import urlparse, parse_qs
        earlier = self.test_date - timedelta(days=1)
        Production.objects.create(factory=self.factory_a, size=self.size_60_120, grade=self.grade_1,
                                  area=D('50.25'), date=earlier, created_by=self.admin)
        Production.objects.create(factory=self.factory_b, size=self.size_60_120, grade=self.grade_1,
                                  area=D('70.00'), date=earlier, created_by=self.admin)
        self.client.force_login(self.viewer_a)
        response = self.client.get('/', {'start': jalali(earlier), 'end': jalali(self.test_date)})
        report = response.context['report']
        self.assertEqual(report['summary_cards']['total_area'], D('1050.25'))
        self.assertEqual([day['report']['summary_cards']['total_area'] for day in report['daily_reports']], [D('50.25'), D('1000.00')])
        for day in report['daily_reports']:
            self.assertEqual([table['factory'].pk for table in day['report']['factory_tables']], [self.factory_a.pk])
            link = day['report']['factory_tables'][0]['rows'][0]['url']
            query = parse_qs(urlparse(link).query)
            self.assertEqual(query['start'], [jalali(day['date'])])
            self.assertEqual(query['end'], [jalali(day['date'])])

    def test_acceptance_scenario_section_10(self):
        """
        Tests the exact scenario described in Section 10:
        Factory A:
          - Grade 1: 800
          - Grade 2: 200
        Factory B:
          - Grade 1: 100
          - Ungraded: 400
        Expected results:
          - Total Factory A: 1,000
          - Total Factory B: 500
          - Cumulative Total: 1,500
          - Grade 1 % Factory A: 80%
          - Grade 1 % Factory B: 20%
          - Grade 1 % Cumulative: 60%
          - Factory A share: ~66.67%
          - Factory B share: ~33.33%
        """
        cleaned_data = {
            'start': self.test_date,
            'end': self.test_date,
            'factory': None,
            'size': None
        }
        report = get_management_report_data(self.admin, cleaned_data, self.client.get('/').context['params'])

        cards = {fc['name']: fc for fc in report['factory_cards']}
        summary = report['summary_cards']

        # 1. Total Factory A: 1,000
        self.assertEqual(cards['کارخانه الف']['total_area'], D('1000.00'))

        # 2. Total Factory B: 500
        self.assertEqual(cards['کارخانه ب']['total_area'], D('500.00'))

        # 3. Cumulative Total: 1,500
        self.assertEqual(summary['total_area'], D('1500.00'))

        # 4. Grade 1 % Factory A: 80%
        self.assertEqual(cards['کارخانه الف']['first_grade_percentage'], D('80.00'))

        # 5. Grade 1 % Factory B: 20%
        self.assertEqual(cards['کارخانه ب']['first_grade_percentage'], D('20.00'))

        # 6. Cumulative Grade 1 %: 60%
        self.assertEqual(summary['first_grade_percentage'], D('60.00'))

        # 7. Factory A share of total: ~66.67%
        self.assertAlmostEqual(float(cards['کارخانه الف']['share_of_total']), 66.6666, places=2)

        # 8. Factory B share of total: ~33.33%
        self.assertAlmostEqual(float(cards['کارخانه ب']['share_of_total']), 33.3333, places=2)

    def test_multi_size_denominator_correctness(self):
        """
        Adding a second size checks that the denominator for each size's grade %
        is strictly that size's total in that factory, and not mixed up.
        """
        size_80_80 = Size.objects.create(width=80, length=80)
        # Add to Factory A: 300 Gr 1, 100 Gr 2 (Total for size 80x80 = 400)
        Production.objects.create(
            factory=self.factory_a, size=size_80_80, grade=self.grade_1,
            area=D('300.00'), date=self.test_date, created_by=self.admin
        )
        Production.objects.create(
            factory=self.factory_a, size=size_80_80, grade=self.grade_2,
            area=D('100.00'), date=self.test_date, created_by=self.admin
        )

        cleaned_data = {'start': self.test_date, 'end': self.test_date}
        report = get_management_report_data(self.admin, cleaned_data, {})

        fa_table = next(t for t in report['factory_tables'] if t['name'] == 'کارخانه الف')
        rows = {r['size_label']: r for r in fa_table['rows']}

        # Size 60x120 row in Factory A (Total = 1000)
        r_60_120 = rows['60 × 120']
        self.assertEqual(r_60_120['total_area'], D('1000.00'))
        g1_cell = next(c for c in r_60_120['grades'] if c['grade'].pk == self.grade_1.pk)
        g2_cell = next(c for c in r_60_120['grades'] if c['grade'].pk == self.grade_2.pk)
        self.assertEqual(g1_cell['percentage'], D('80.00'))
        self.assertEqual(g2_cell['percentage'], D('20.00'))

        # Size 80x80 row in Factory A (Total = 400)
        r_80_80 = rows['80 × 80']
        self.assertEqual(r_80_80['total_area'], D('400.00'))
        g1_cell_80 = next(c for c in r_80_80['grades'] if c['grade'].pk == self.grade_1.pk)
        g2_cell_80 = next(c for c in r_80_80['grades'] if c['grade'].pk == self.grade_2.pk)
        # 300 / 400 = 75%
        self.assertEqual(g1_cell_80['percentage'], D('75.00'))
        # 100 / 400 = 25%
        self.assertEqual(g2_cell_80['percentage'], D('25.00'))

        # Factory A Footer row: total = 1400.
        # Grade 1 total in Factory A = 800 + 300 = 1100 -> 1100 / 1400 = 78.57%
        footer_g1 = next(c for c in fa_table['footer']['grades'] if c['grade'].pk == self.grade_1.pk)
        self.assertAlmostEqual(float(footer_g1['percentage']), 78.57, places=2)

    def test_permission_scoping(self):
        """
        A user with access only to Factory A must not see Factory B data.
        """
        self.client.force_login(self.viewer_a)
        response = self.client.get('/', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200)

        report = response.context['report']
        factories_in_report = [f['name'] for f in report['factory_cards']]
        self.assertIn('کارخانه الف', factories_in_report)
        self.assertNotIn('کارخانه ب', factories_in_report)

        # Total should only reflect Factory A (1,000)
        self.assertEqual(report['summary_cards']['total_area'], D('1000.00'))

    def test_soft_deleted_records_excluded(self):
        """
        Soft-deleted production records (deleted_at is set) must not appear in the report.
        """
        Production.objects.create(
            factory=self.factory_a, size=self.size_60_120, grade=self.grade_1,
            area=D('500.00'), date=self.test_date, created_by=self.admin,
            deleted_at=timezone.now()
        )
        cleaned_data = {'start': self.test_date, 'end': self.test_date}
        report = get_management_report_data(self.admin, cleaned_data, {})
        # Total must remain 1500, not 2000
        self.assertEqual(report['summary_cards']['total_area'], D('1500.00'))

    def test_unconfirmed_excel_rows_excluded(self):
        """
        Staging ProductionImportRow records must not appear in management report
        until confirmed into actual Production records.
        """
        batch = ProductionImportBatch.objects.create(
            factory=self.factory_a, date=self.test_date, uploaded_by=self.admin,
            status='pending'
        )
        ProductionImportRow.objects.create(
            batch=batch, excel_row=2, raw_description='تست',
            size=self.size_60_120, grade=self.grade_1, area=D('999.00'),
            status='ok'
        )
        cleaned_data = {'start': self.test_date, 'end': self.test_date}
        report = get_management_report_data(self.admin, cleaned_data, {})
        self.assertEqual(report['summary_cards']['total_area'], D('1500.00'))

    def test_zero_production_factory(self):
        """
        A permitted factory with zero production must be shown with 0 area
        and 'بدون تولید در این بازه'.
        """
        factory_c = Factory.objects.create(name='کارخانه ج')
        cleaned_data = {'start': self.test_date, 'end': self.test_date}
        report = get_management_report_data(self.admin, cleaned_data, {})

        card_c = next(fc for fc in report['factory_cards'] if fc['name'] == 'کارخانه ج')
        self.assertEqual(card_c['total_area'], D('0'))
        self.assertFalse(card_c['has_production'])
        self.assertEqual(card_c['share_of_total'], D('0.00'))
        self.assertIsNone(card_c['first_grade_percentage'])

        # Check rendered HTML for factory C
        resp = self.client.get(f'/management-preview/?start={jalali(self.test_date)}&end={jalali(self.test_date)}', HTTP_HOST='127.0.0.1')
        self.assertContains(resp, 'بدون تولید در این بازه')

    def test_invalid_date_range(self):
        """
        Start date after end date should show Persian error and return 400 status.
        """
        resp = self.client.get('/?start=1405/06/20&end=1405/06/10', HTTP_HOST='127.0.0.1')
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, 'پایان بازه نباید قبل از شروع تاریخ باشد', status_code=400)

    def test_dynamic_new_grade(self):
        """
        Adding a new grade to the database dynamically adds it as a column
        in both per-factory and aggregated tables.
        """
        grade_special = Grade.objects.create(name='درجه صادراتی', rank=5, color='#990000')
        Production.objects.create(
            factory=self.factory_a, size=self.size_60_120, grade=grade_special,
            area=D('50.00'), date=self.test_date, created_by=self.admin
        )
        cleaned_data = {'start': self.test_date, 'end': self.test_date}
        report = get_management_report_data(self.admin, cleaned_data, {})

        grade_names = [g.name for g in report['grades']]
        self.assertIn('درجه صادراتی', grade_names)

        fa_table = next(t for t in report['factory_tables'] if t['name'] == 'کارخانه الف')
        row = fa_table['rows'][0]
        special_cell = next(c for c in row['grades'] if c['grade'].pk == grade_special.pk)
        self.assertEqual(special_cell['area'], D('50.00'))

    def test_management_grade_columns_follow_configured_rank(self):
        grade_6 = Grade.objects.create(name='درجه ۶', rank=4, color='#445566')
        self.grade_ungraded.rank = 3
        self.grade_ungraded.save(update_fields=['rank'])
        report = get_management_report_data(self.admin, {'start': self.test_date, 'end': self.test_date}, {})
        names = [grade.name for grade in report['grades']]
        self.assertLess(names.index('آنگرید'), names.index('درجه ۶'))

    def test_grade_report_and_summary_follow_configured_rank(self):
        grade_6 = Grade.objects.create(name='درجه ۶', rank=4, color='#445566')
        self.grade_ungraded.rank = 3
        self.grade_ungraded.save(update_fields=['rank'])
        Production.objects.create(factory=self.factory_a, size=self.size_60_120, grade=grade_6,
                                  area=D('25.00'), date=self.test_date, created_by=self.admin)
        data = {'start': self.test_date, 'end': self.test_date, 'group': 'grade'}
        summary = summarize(self.admin, data, QueryDict('', mutable=True))
        labels = [item['label'] for item in summary['grades']]
        self.assertLess(labels.index('آنگرید'), labels.index('درجه ۶'))
        table = report_table(summary, data)
        row_labels = [row['cells'][0] for row in table['body']]
        self.assertLess(row_labels.index('آنگرید'), row_labels.index('درجه ۶'))

    def test_unauthenticated_redirect(self):
        """
        Unauthenticated visit to / should redirect to login with ?next=/
        """
        self.client.logout()
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp['Location'])
        self.assertIn('next=', resp['Location'])

    def test_overview_path_accessible(self):
        """
        The previous dashboard is preserved and accessible at /overview/
        """
        resp = self.client.get('/overview/', HTTP_HOST='127.0.0.1')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'نمای کلی تولید')

    def test_sidebar_navigation_order(self):
        """
        Management report is the first option in the navigation menu.
        """
        resp = self.client.get('/', HTTP_HOST='127.0.0.1')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        pos_mgmt = content.find('گزارش مدیریتی')
        pos_overview = content.find('نمای کلی تولید')
        pos_reports = content.find('گزارش‌های تولید')
        self.assertTrue(pos_mgmt < pos_overview < pos_reports)

    def test_management_report_section_order(self):
        """
        The section 'ترکیب درجات به تفکیک کارخانه و سایز' must be placed at the highest position
        in the report content, before summary cards, factory cards, and charts.
        """
        resp = self.client.get(f'/management-preview/?start={jalali(self.test_date)}&end={jalali(self.test_date)}', HTTP_HOST='127.0.0.1')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        pos_tables = content.find('ترکیب درجات به تفکیک کارخانه و سایز')
        pos_aggregated = content.find('تجمیع تمام کارخانه‌های فیلترشده')
        pos_kpis = content.find('شاخص‌های کلیدی تولید')
        pos_factories = content.find('عملکرد به تفکیک کارخانه‌ها')
        pos_charts = content.find('نمودارهای تحلیلی')

        self.assertNotEqual(pos_tables, -1)
        self.assertNotEqual(pos_aggregated, -1)
        self.assertNotEqual(pos_kpis, -1)
        self.assertNotEqual(pos_factories, -1)
        self.assertNotEqual(pos_charts, -1)

        self.assertTrue(
            pos_tables < pos_aggregated < pos_kpis < pos_factories < pos_charts,
            f"Incorrect order: tables={pos_tables}, aggregated={pos_aggregated}, kpis={pos_kpis}, factories={pos_factories}, charts={pos_charts}"
        )

    def test_filter_modal_present_and_inline_panel_removed(self):
        """
        Inline filter-panel should be removed, filter modal should be present with trigger buttons,
        and invalid submissions should automatically render the modal open.
        """
        # 1. Valid request
        resp = self.client.get(f'/management-preview/?start={jalali(self.test_date)}&end={jalali(self.test_date)}', HTTP_HOST='127.0.0.1')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Inline panel removed
        self.assertNotIn('class="filter-panel"', content)

        # Trigger buttons present
        self.assertIn('id="open-filter-modal"', content)
        self.assertIn('فیلتر گزارش', content)

        # Quick factory buttons present, banner removed
        self.assertNotIn('class="mgmt-banner"', content)
        self.assertNotIn('id="open-filter-banner-btn"', content)
        self.assertNotIn('تغییر فیلترها', content)
        self.assertIn('class="factory-quick-bar"', content)
        self.assertIn('همه کارخانه‌ها', content)
        self.assertIn('کارخانه الف', content)
        self.assertIn('کارخانه ب', content)

        # Modal is present and hidden by default on valid page load
        self.assertIn('id="filter-modal"', content)
        self.assertIn('id="filter-modal" class="filter-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="filter-modal-title" hidden', content)
        self.assertIn('name="start"', content)
        self.assertIn('name="end"', content)
        self.assertIn('name="factory"', content)
        self.assertIn('name="size"', content)
        self.assertIn('value="today"', content)

        # 2. Default date is yesterday when accessing /management-preview/ without parameters
        resp_default = self.client.get('/management-preview/', HTTP_HOST='127.0.0.1')
        self.assertEqual(resp_default.status_code, 200)
        yesterday_str = jalali(period('yesterday')[0])
        self.assertEqual(resp_default.context['params']['start'], yesterday_str)
        self.assertEqual(resp_default.context['params']['end'], yesterday_str)

        # 3. Invalid date range request: modal should not have 'hidden' attribute
        resp_invalid = self.client.get('/management-preview/?start=1405/06/20&end=1405/06/10', HTTP_HOST='127.0.0.1')
        self.assertEqual(resp_invalid.status_code, 400)
        content_invalid = resp_invalid.content.decode('utf-8')

        # Modal is open (not hidden) so the user immediately sees the error and form
        self.assertIn('id="filter-modal" class="filter-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="filter-modal-title"', content_invalid)
        # Check that it doesn't contain 'hidden' on the modal element
        modal_tag = content_invalid[content_invalid.find('id="filter-modal"'):content_invalid.find('id="filter-modal"') + 150]
        self.assertNotIn('hidden', modal_tag)
        self.assertIn('پایان بازه نباید قبل از شروع تاریخ باشد', content_invalid)

    def test_mobile_cards_view_present(self):
        """
        Both desktop table view and mobile card view should be rendered in the DOM,
        so mobile users see responsive cards without horizontal scrolling.
        """
        resp = self.client.get(f'/management-preview/?start={jalali(self.test_date)}&end={jalali(self.test_date)}', HTTP_HOST='127.0.0.1')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        for item in ['desktop-table-view', 'mgmt-mobile-cards', 'mgmt-m-card', 'mgmt-m-grades-grid', 'mgmt-m-footer-card']:
            self.assertIn(item, content)
