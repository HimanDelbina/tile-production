import uuid
import os
from decimal import Decimal as D
from datetime import date
from io import BytesIO
import openpyxl

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError

from production.models import (
    Factory, Size, Grade, TechnicalType, Profile,
    Production, Audit, ProductionImportBatch, ProductionImportRow
)
from production.importing.parser import parse_description
from production.importing.matcher import match_and_evaluate_row


class RegressionTests(TestCase):
    """Regression tests for Bugs A, B, and C identified in current codebase."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('admin_reg', 'admin@example.test', 'Pass-12345-Admin!')
        Profile.objects.create(user=cls.admin, role='admin')

        cls.factory1 = Factory.objects.create(name='کارخانه آزمایش ۱')
        cls.factory2 = Factory.objects.create(name='کارخانه آزمایش ۲')

        cls.size = Size.objects.create(width=60, length=120, active=True)
        cls.grade1 = Grade.objects.create(name='درجه 1', rank=1, color='#159b9a', active=True)
        cls.tech = TechnicalType.objects.create(name='پرسلان نانو پولیش 10MIL')

        cls.entry_user = get_user_model().objects.create_user('entry_reg', password='Pass-12345-Entry!')
        p_entry = Profile.objects.create(user=cls.entry_user, role='entry')
        p_entry.factories.add(cls.factory1)

        cls.viewer_user = get_user_model().objects.create_user('viewer_reg', password='Pass-12345-Viewer!')
        p_view = Profile.objects.create(user=cls.viewer_user, role='viewer')
        p_view.factories.add(cls.factory1)

    def create_excel_file(self, rows_data, filename="test_file.xlsx", sheet_name="تولید"):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
        ws.append(["شرح کالا", "جمع تولید", "متراژ"])
        for r in rows_data:
            ws.append(r)
        out = BytesIO()
        wb.save(out)
        out.seek(0)
        return SimpleUploadedFile(filename, out.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_regression_bug_a_duplicate_file_before_confirmation_prevented(self):
        """
        Bug A Regression:
        A file for the same factory and date was uploaded twice BEFORE either was confirmed.
        Then both were confirmed, leading to duplicate production records.
        """
        self.client.force_login(self.admin)
        excel_content = [
            ["پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1", 100, 216.0],
        ]

        excel_obj = self.create_excel_file(excel_content, filename="prod.xlsx")
        raw_bytes = excel_obj.read()
        file1 = SimpleUploadedFile("prod.xlsx", raw_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # Upload 1
        res1 = self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': file1,
        })
        self.assertEqual(res1.status_code, 302)
        batch1 = ProductionImportBatch.objects.latest('pk')

        # Test upload redirection when pending batch already exists
        file2 = SimpleUploadedFile("prod.xlsx", raw_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        res2 = self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': file2,
        })
        self.assertEqual(res2.status_code, 302)
        # Upload redirects to existing preview rather than creating duplicate batch
        self.assertIn(str(batch1.token), res2.url)

        # Now simulate two separate pending batches that were created (e.g. concurrent uploads or prior to check)
        batch2 = ProductionImportBatch.objects.create(
            factory=self.factory1,
            date=batch1.date,
            uploaded_by=self.admin,
            original_file=batch1.original_file,
            sheet_name=batch1.sheet_name,
            file_hash=batch1.file_hash,
            status='pending',
        )
        ProductionImportRow.objects.create(
            batch=batch2,
            excel_row=2,
            raw_description="ردیف مشابه",
            size=self.size,
            grade=self.grade1,
            technical_type=self.tech,
            area=D('216.00'),
            status='ok',
        )

        # Confirm batch 1
        confirm_res1 = self.client.post(reverse('import_confirm', args=[batch1.token]))
        self.assertEqual(confirm_res1.status_code, 302)
        batch1.refresh_from_db()
        self.assertEqual(batch1.status, 'confirmed')
        initial_prod_count = Production.objects.filter(factory=self.factory1).count()
        self.assertEqual(initial_prod_count, 1)

        # Now attempt to confirm batch 2: MUST BE REJECTED!
        confirm_res2 = self.client.post(reverse('import_confirm', args=[batch2.token]), follow=True)
        self.assertEqual(confirm_res2.status_code, 200)
        batch2.refresh_from_db()
        self.assertNotEqual(batch2.status, 'confirmed')
        self.assertEqual(batch2.status, 'pending')
        # No duplicate production record must be created!
        self.assertEqual(Production.objects.filter(factory=self.factory1).count(), initial_prod_count)
        # Response must contain a friendly Persian message
        self.assertTrue(
            any("قبلاً" in m.message or "تکراری" in m.message for m in confirm_res2.context['messages'])
        )

        # Verify that the same file for a DIFFERENT factory is allowed
        file_diff_fac = self.create_excel_file(excel_content, filename="prod.xlsx")
        res_diff_fac = self.client.post(reverse('import_upload'), {
            'factory': self.factory2.pk,
            'date': '1405/06/18',
            'file': file_diff_fac,
        })
        self.assertEqual(res_diff_fac.status_code, 302)
        batch_diff_fac = ProductionImportBatch.objects.latest('pk')
        confirm_diff = self.client.post(reverse('import_confirm', args=[batch_diff_fac.token]))
        self.assertEqual(confirm_diff.status_code, 302)
        batch_diff_fac.refresh_from_db()
        self.assertEqual(batch_diff_fac.status, 'confirmed')

    def test_regression_bug_b_negative_quantity_remains_error_after_reprocess(self):
        """
        Bug B Regression:
        Row with negative production quantity (e.g. -50) was initially marked as 'error'.
        After calling 'reprocess', its status incorrectly turned into 'ok' and could be confirmed!
        """
        self.client.force_login(self.admin)
        excel_file = self.create_excel_file([
            ["پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1", -50, 216.0],
        ])

        res = self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': excel_file,
        })
        self.assertEqual(res.status_code, 302)

        batch = ProductionImportBatch.objects.latest('pk')
        row = batch.rows.first()
        self.assertEqual(row.status, 'error')
        self.assertIn("منفی", row.error_message)

        # Trigger reprocess
        reprocess_res = self.client.post(reverse('import_preview', args=[batch.token]), {
            'action': 'reprocess',
        })
        self.assertEqual(reprocess_res.status_code, 302)

        row.refresh_from_db()
        # MUST REMAIN ERROR!
        self.assertEqual(row.status, 'error')
        self.assertIn("منفی", row.error_message)

        # Confirmation must be blocked
        confirm_res = self.client.post(reverse('import_confirm', args=[batch.token]))
        self.assertEqual(confirm_res.status_code, 302)
        batch.refresh_from_db()
        self.assertNotEqual(batch.status, 'confirmed')
        self.assertEqual(Production.objects.filter(factory=self.factory1).count(), 0)

    def test_regression_bug_c_confirmed_batch_cannot_be_modified_by_save_rows(self):
        """
        Bug C Regression:
        After a batch was confirmed, the 'save_rows' action could still change the preview meterage
        from 2.16 to 99, while the final Production record remained 2.16, creating inconsistency.
        """
        self.client.force_login(self.admin)
        excel_file = self.create_excel_file([
            ["پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1", 1, 2.16],
        ])

        self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': excel_file,
        })
        batch = ProductionImportBatch.objects.latest('pk')
        row = batch.rows.first()
        self.assertEqual(row.status, 'ok')
        self.assertEqual(row.area, D('2.16'))

        # Confirm the batch
        self.client.post(reverse('import_confirm', args=[batch.token]))
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'confirmed')
        row.refresh_from_db()
        self.assertIsNotNone(row.production)
        self.assertEqual(row.production.area, D('2.16'))

        # Now attempt to attack / tamper with save_rows on the confirmed batch!
        tamper_data = {
            'action': 'save_rows',
            f'r_{row.pk}-row_id': row.pk,
            f'r_{row.pk}-size': self.size.pk,
            f'r_{row.pk}-grade': self.grade1.pk,
            f'r_{row.pk}-technical_type': self.tech.pk,
            f'r_{row.pk}-area': '99.00',
            f'r_{row.pk}-notes': 'دستکاری پس از تأیید',
        }
        res_tamper = self.client.post(reverse('import_preview', args=[batch.token]), tamper_data, follow=True)
        self.assertEqual(res_tamper.status_code, 200)

        # Verify that row.area DID NOT CHANGE!
        row.refresh_from_db()
        self.assertEqual(row.area, D('2.16'))
        self.assertNotEqual(row.area, D('99.00'))

        # Production area must also remain 2.16
        row.production.refresh_from_db()
        self.assertEqual(row.production.area, D('2.16'))

        # Also verify reprocess is rejected
        self.client.post(reverse('import_preview', args=[batch.token]), {'action': 'reprocess'})
        row.refresh_from_db()
        self.assertEqual(row.area, D('2.16'))

    def test_reconfirm_same_batch_is_idempotent(self):
        """Confirming the exact same confirmed batch a second time creates no duplicate."""
        self.client.force_login(self.admin)
        excel_file = self.create_excel_file([
            ["پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1", 10, 21.6],
        ])
        self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': excel_file,
        })
        batch = ProductionImportBatch.objects.latest('pk')
        self.client.post(reverse('import_confirm', args=[batch.token]))
        self.assertEqual(Production.objects.filter(factory=self.factory1).count(), 1)
        self.assertEqual(Audit.objects.count(), 1)

        # Confirm again
        self.client.post(reverse('import_confirm', args=[batch.token]))
        self.assertEqual(Production.objects.filter(factory=self.factory1).count(), 1)
        self.assertEqual(Audit.objects.count(), 1)

    def test_secure_file_download_access_control(self):
        """Only users with appropriate permissions can download the original excel file."""
        self.client.force_login(self.admin)
        excel_file = self.create_excel_file([
            ["پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1", 10, 21.6],
        ])
        self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': excel_file,
        })
        batch = ProductionImportBatch.objects.latest('pk')

        # Admin can download
        res_admin = self.client.get(reverse('import_file_download', args=[batch.token]))
        self.assertEqual(res_admin.status_code, 200)
        self.assertEqual(res_admin['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        # User from factory 2 cannot download
        other_user = get_user_model().objects.create_user('other_fac_user', password='Password-123!')
        p = Profile.objects.create(user=other_user, role='entry')
        p.factories.add(self.factory2)
        self.client.force_login(other_user)
        res_other = self.client.get(reverse('import_file_download', args=[batch.token]))
        self.assertEqual(res_other.status_code, 403)

        # Unauthenticated user redirected to login
        self.client.logout()
        res_anon = self.client.get(reverse('import_file_download', args=[batch.token]))
        self.assertEqual(res_anon.status_code, 302)

    def test_production_settings_enforces_postgres_and_secret_key(self):
        """Production configuration must raise ImproperlyConfigured when Postgres vars or secret key missing."""
        import importlib
        from unittest.mock import patch
        from django.core.exceptions import ImproperlyConfigured

        # Missing secret key in production
        with patch.dict(os.environ, {'DJANGO_ENV': 'production', 'DJANGO_SECRET_KEY': '', 'BUILDING_STATIC': '0'}, clear=False):
            with self.assertRaises(ImproperlyConfigured):
                import config.settings as s
                importlib.reload(s)

        # Weak secret key in production
        with patch.dict(os.environ, {'DJANGO_ENV': 'production', 'DJANGO_SECRET_KEY': 'too-short', 'BUILDING_STATIC': '0'}, clear=False):
            with self.assertRaises(ImproperlyConfigured):
                import config.settings as s
                importlib.reload(s)

        # Missing postgres password in production
        with patch.dict(os.environ, {
            'DJANGO_ENV': 'production',
            'DJANGO_SECRET_KEY': 'a' * 55,
            'POSTGRES_HOST': 'localhost',
            'POSTGRES_DB': 'db',
            'POSTGRES_USER': 'user',
            'POSTGRES_PASSWORD': '',
            'BUILDING_STATIC': '0'
        }, clear=False):
            with self.assertRaises(ImproperlyConfigured):
                import config.settings as s
                importlib.reload(s)

    def test_healthcheck_exempt_from_ssl_redirect(self):
        """Health check route /health/ must be exempt from SSL redirect."""
        from django.conf import settings
        self.assertTrue(any('health' in str(pattern) for pattern in settings.SECURE_REDIRECT_EXEMPT))
        res = self.client.get('/health/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {'status': 'ok'})
