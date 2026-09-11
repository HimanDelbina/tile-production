import uuid
import os
from decimal import Decimal as D
from datetime import date
from io import BytesIO
import openpyxl

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from production.models import (
    Factory, Size, Grade, TechnicalType, Profile,
    Production, Audit, ProductionImportBatch, ProductionImportRow
)
from production.importing.parser import (
    normalize_text, extract_size_spec, extract_grade_spec,
    extract_technical_type_spec, extract_piece_area, parse_description
)
from production.importing.matcher import (
    match_size, match_grade, match_technical_type, match_and_evaluate_row
)
from production.importing.reader import read_excel_import_file


class ParserAndMatchingTests(TestCase):
    """Tests for text normalization, parsing, and database matching."""

    def test_sample_a_extraction(self):
        """Case A: پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا لايت گري نيو 60*120 CH مهتاب درجه1"""
        raw = "پرسلان  نانو پوليش 10MIL مساحت 2.16 صاحارا لايت گري نيو 60*120 CH مهتاب  درجه1"
        res = parse_description(raw)
        self.assertEqual(res['size'], (60, 120))
        self.assertEqual(res['grade_code'], '1')
        self.assertEqual(res['technical_type_name'], 'پرسلان نانو پولیش 10MIL')
        self.assertEqual(res['piece_area'], D('2.16'))
        
        # Test evaluation with quantity and area
        eval_res = match_and_evaluate_row(res, quantity=D(597), area=D('1289.52'))
        self.assertEqual(eval_res['area'], D('1289.52'))
        self.assertEqual(len(eval_res['warnings']), 0)

    def test_sample_b_extraction(self):
        """Case B: پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا لايت گري نيو 60*120 CH ARTISTدرجهUNGRADE"""
        raw = "پرسلان  نانو پوليش 10MIL مساحت 2.16 صاحارا لايت گري نيو 60*120 CH ARTISTدرجهUNGRADE"
        res = parse_description(raw)
        self.assertEqual(res['size'], (60, 120))
        self.assertEqual(res['grade_code'], 'UNGRADE')
        self.assertEqual(res['technical_type_name'], 'پرسلان نانو پولیش 10MIL')

    def test_sample_c_extraction(self):
        """Case C: پرسلان نانو پوليش 10MIL مساحت 2.16  YT 805مهتاب 60*120 درجه1 (805 not mistaken for size)"""
        raw = "پرسلان  نانو پوليش 10MIL مساحت 2.16  YT 805مهتاب 60*120 درجه1"
        res = parse_description(raw)
        self.assertEqual(res['size'], (60, 120))
        self.assertEqual(res['grade_code'], '1')
        self.assertEqual(res['technical_type_name'], 'پرسلان نانو پولیش 10MIL')

    def test_sample_d_extraction(self):
        """Case D: 12MIL نانوپوليش مساحت 2کارولين وايت زئوس 100*100 CH درجه6"""
        raw = "12MIL نانوپوليش مساحت 2کارولين وايت زئوس 100*100 CH  درجه6"
        res = parse_description(raw)
        self.assertEqual(res['size'], (100, 100))
        self.assertEqual(res['grade_code'], '6')
        self.assertEqual(res['technical_type_name'], 'نانو پولیش 12MIL')
        self.assertEqual(res['piece_area'], D('2'))
        # Must not guess 'پرسلان'
        self.assertNotIn('پرسلان', res['technical_type_name'])

    def test_all_14_rows_from_attached_excel(self):
        file_path = os.path.join(os.path.dirname(__file__), 'fixtures', 'اکسل.xlsx')
        if not os.path.exists(file_path):
            file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'imports', 'اکسل.xlsx')
        if not os.path.exists(file_path):
            self.skipTest("fixtures/اکسل.xlsx not found")
            
        rows = read_excel_import_file(file_path)
        self.assertEqual(len(rows), 14)
        
        for idx, r in enumerate(rows[:10], start=2):
            parsed = parse_description(r['raw_description'])
            self.assertEqual(parsed['size'], (60, 120), f"Row {idx} size mismatch")
            self.assertEqual(parsed['technical_type_name'], 'پرسلان نانو پولیش 10MIL', f"Row {idx} tech mismatch")
            self.assertEqual(parsed['piece_area'], D('2.16'))
            # Check quantity * piece_area == area
            self.assertEqual(r['quantity'] * parsed['piece_area'], r['area'])

        for idx, r in enumerate(rows[10:], start=12):
            parsed = parse_description(r['raw_description'])
            self.assertEqual(parsed['size'], (100, 100), f"Row {idx} size mismatch")
            self.assertEqual(parsed['technical_type_name'], 'نانو پولیش 12MIL', f"Row {idx} tech mismatch")
            self.assertEqual(parsed['piece_area'], D('2'))
            self.assertEqual(r['quantity'] * parsed['piece_area'], r['area'])

    def test_independent_extraction_empty_db(self):
        """Test that parser extracts values even when database tables (Size, Grade, TechType) are empty."""
        Size.objects.all().delete()
        Grade.objects.all().delete()
        TechnicalType.objects.all().delete()
        
        raw = "پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1"
        res = parse_description(raw)
        self.assertEqual(res['size'], (60, 120))
        self.assertEqual(res['grade_code'], '1')
        self.assertEqual(res['technical_type_name'], 'پرسلان نانو پولیش 10MIL')
        
        # When evaluating against empty DB, distinct messages must be generated
        eval_res = match_and_evaluate_row(res, quantity=D(10), area=D('21.6'))
        self.assertIsNone(eval_res['size'])
        self.assertIsNone(eval_res['grade'])
        self.assertIsNone(eval_res['technical_type'])
        self.assertEqual(eval_res['status'], 'error')
        self.assertIn("سایز ۶۰×۱۲۰ استخراج شد، اما در اطلاعات پایه تعریف نشده است", eval_res['error_message'])
        self.assertIn("درجه ۱ استخراج شد، اما گزینه متناظر تعریف نشده است", eval_res['error_message'])
        self.assertIn("نوع فنی «پرسلان نانو پولیش 10MIL»", eval_res['error_message'])

    def test_matching_after_creating_base_data(self):
        """Test matching after creating base data records."""
        Size.objects.all().delete()
        Grade.objects.all().delete()
        TechnicalType.objects.all().delete()

        raw = "پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1"
        res = parse_description(raw)
        eval_before = match_and_evaluate_row(res, quantity=D(10), area=D('21.6'))
        self.assertFalse(eval_before['is_ok'])

        # Create base records
        s = Size.objects.create(width=60, length=120, active=True)
        g = Grade.objects.create(name='درجه 1', rank=1, color='#159b9a', active=True)
        tt = TechnicalType.objects.create(name='پرسلان نانو پولیش 10MIL')

        eval_after = match_and_evaluate_row(res, quantity=D(10), area=D('21.6'))
        self.assertTrue(eval_after['is_ok'])
        self.assertEqual(eval_after['size'], s)
        self.assertEqual(eval_after['grade'], g)
        self.assertEqual(eval_after['technical_type'], tt)

    def test_ungrade_and_grade_6_with_arbitrary_ranks(self):
        """Ensure grade matching uses names, not rank or id."""
        Grade.objects.all().delete()
        # In sample DB, Grade 6 has rank 3, Ungrade has rank 4
        g6 = Grade.objects.create(name='درجه 6', rank=3, color='#159b9a', active=True)
        gun = Grade.objects.create(name='آنگرید', rank=4, color='#159b9a', active=True)
        g1 = Grade.objects.create(name='درجه 1', rank=1, color='#159b9a', active=True)

        matched_6, _ = match_grade('6')
        self.assertEqual(matched_6, g6)

        matched_un, _ = match_grade('UNGRADE')
        self.assertEqual(matched_un, gun)

        matched_1, _ = match_grade('1')
        self.assertEqual(matched_1, g1)

    def test_reverse_size_matching(self):
        """If only reverse size exists in DB (e.g. 120x60 instead of 60x120), match it and mark is_reversed."""
        Size.objects.all().delete()
        s_rev = Size.objects.create(width=120, length=60, active=True)

        matched, is_rev, msg = match_size(60, 120)
        self.assertEqual(matched, s_rev)
        self.assertTrue(is_rev)
        self.assertIn("معکوس", msg)

    def test_ambiguous_and_missing_sizes(self):
        """Multiple distinct sizes in description should report ambiguity; missing size should report missing."""
        res_amb = parse_description("کاشی پرسلان 60*120 و 80*80 درجه1")
        self.assertIsNone(res_amb['size'])
        self.assertIn("چند سایز متفاوت", res_amb['errors'][0])

        res_none = parse_description("کاشی پرسلان درجه1")
        self.assertIsNone(res_none['size'])
        self.assertIn("سایز در شرح کالا پیدا نشد", res_none['errors'][0])

    def test_unknown_grade_does_not_become_grade_1(self):
        """Unknown grade must not silently fallback to Grade 1."""
        Grade.objects.all().delete()
        g1 = Grade.objects.create(name='درجه 1', rank=1, color='#159b9a', active=True)
        
        matched, msg = match_grade('99')
        self.assertIsNone(matched)
        self.assertNotEqual(matched, g1)
        self.assertIn("تعریف نشده است", msg)


class ImportWorkflowIntegrationTests(TestCase):
    """Integration tests for Excel import workflow: upload, preview, reprocess, and confirm."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('admin_imp', 'admin@example.test', 'Pass-12345-Admin!')
        Profile.objects.create(user=cls.admin, role='admin')

        cls.factory1 = Factory.objects.create(name='کارخانه ۱')
        cls.factory2 = Factory.objects.create(name='کارخانه ۲')

        cls.entry_user = get_user_model().objects.create_user('entry_imp', password='Pass-12345-Entry!')
        p_entry = Profile.objects.create(user=cls.entry_user, role='entry')
        p_entry.factories.add(cls.factory1)

        cls.viewer_user = get_user_model().objects.create_user('viewer_imp', password='Pass-12345-Viewer!')
        p_view = Profile.objects.create(user=cls.viewer_user, role='viewer')
        p_view.factories.add(cls.factory1)

        cls.user_no_profile = get_user_model().objects.create_user('noprofile', password='Pass-12345-None!')

        # Initial grades in DB
        cls.g1 = Grade.objects.create(name='درجه 1', rank=1, color='#159b9a', active=True)
        cls.g6 = Grade.objects.create(name='درجه 6', rank=3, color='#159b9a', active=True)
        cls.gun = Grade.objects.create(name='آنگرید', rank=4, color='#159b9a', active=True)

    def create_excel_file(self, rows_data):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "تولید"
        ws.append(["شرح کالا", "جمع تولید", "متراژ"])
        for r in rows_data:
            ws.append(r)
        out = BytesIO()
        wb.save(out)
        out.seek(0)
        return SimpleUploadedFile("test_import.xlsx", out.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_viewer_cannot_upload_preview_or_confirm(self):
        """Viewer role must be forbidden from all import endpoints."""
        self.client.force_login(self.viewer_user)
        upload_res = self.client.get(reverse('import_upload'))
        self.assertEqual(upload_res.status_code, 403)

        fake_token = uuid.uuid4()
        preview_res = self.client.get(reverse('import_preview', args=[fake_token]))
        self.assertEqual(preview_res.status_code, 403)

        confirm_res = self.client.post(reverse('import_confirm', args=[fake_token]))
        self.assertEqual(confirm_res.status_code, 403)

    def test_user_without_profile_cannot_upload_and_no_profile_auto_created(self):
        """User without profile must be denied and not automatically granted entry profile."""
        self.client.force_login(self.user_no_profile)
        res = self.client.get(reverse('import_upload'))
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Profile.objects.filter(user=self.user_no_profile).exists())

    def test_upload_form_empty_for_user_without_factories(self):
        """Entry user with no factories assigned must see empty factory queryset."""
        user_no_fac = get_user_model().objects.create_user('nofac', password='Pass-12345-NoFac!')
        Profile.objects.create(user=user_no_fac, role='entry')
        from production.forms import ExcelUploadForm
        form = ExcelUploadForm(user=user_no_fac)
        self.assertEqual(form.fields['factory'].queryset.count(), 0)

    def test_successful_upload_and_preview_flow(self):
        """Upload an Excel file with valid rows and verify preview rendering."""
        self.client.force_login(self.admin)
        excel_file = self.create_excel_file([
            ["پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا لايت گري نيو 60*120 CH مهتاب درجه1", 597, 1289.52],
            ["12MIL نانوپوليش مساحت 2کارولين وايت زئوس 100*100 CH درجه6", 92, 184],
        ])

        res = self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': excel_file,
        })
        self.assertEqual(res.status_code, 302)

        batch = ProductionImportBatch.objects.filter(factory=self.factory1).first()
        self.assertIsNotNone(batch)
        self.assertEqual(batch.rows.count(), 2)

        # View preview page
        preview_res = self.client.get(reverse('import_preview', args=[batch.token]))
        self.assertEqual(preview_res.status_code, 200)
        # Because Size 60x120 and 100x100 are not in DB, missing items should be listed
        self.assertContains(preview_res, "60×120")
        self.assertContains(preview_res, "100×100")
        self.assertContains(preview_res, "پرسلان نانو پولیش 10MIL")
        self.assertContains(preview_res, "نانو پولیش 12MIL")

    def test_admin_create_missing_base_data_and_auto_rematch(self):
        """Admin can submit 'create_missing_base' and preview immediately updates to ok."""
        self.client.force_login(self.admin)
        excel_file = self.create_excel_file([
            ["پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1", 10, 21.6],
        ])
        self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': excel_file,
        })
        batch = ProductionImportBatch.objects.filter(factory=self.factory1).first()
        row = batch.rows.first()
        self.assertEqual(row.status, 'error')

        # Admin creates base data
        res = self.client.post(reverse('import_preview', args=[batch.token]), {
            'action': 'create_missing_base',
            'sizes': ['60×120'],
            'tech_types': ['پرسلان نانو پولیش 10MIL'],
        })
        self.assertEqual(res.status_code, 302)

        # Verify base records created
        self.assertTrue(Size.objects.filter(width=60, length=120).exists())
        self.assertTrue(TechnicalType.objects.filter(name='پرسلان نانو پولیش 10MIL').exists())

        # Verify row is now OK!
        row.refresh_from_db()
        self.assertEqual(row.status, 'ok')
        self.assertEqual(row.size.width, 60)
        self.assertEqual(row.technical_type.name, 'پرسلان نانو پولیش 10MIL')

    def test_non_admin_cannot_create_base_data(self):
        """Regular entry user cannot trigger create_missing_base."""
        self.client.force_login(self.entry_user)
        excel_file = self.create_excel_file([
            ["پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1", 10, 21.6],
        ])
        self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': excel_file,
        })
        batch = ProductionImportBatch.objects.filter(uploaded_by=self.entry_user).first()
        
        res = self.client.post(reverse('import_preview', args=[batch.token]), {
            'action': 'create_missing_base',
            'sizes': ['60×120'],
            'tech_types': ['پرسلان نانو پولیش 10MIL'],
        })
        self.assertEqual(res.status_code, 403)

    def test_reprocess_preserves_manual_edits(self):
        """Reprocessing re-runs extraction but preserves manual overrides."""
        self.client.force_login(self.admin)
        Size.objects.create(width=60, length=120, active=True)
        s_custom = Size.objects.create(width=80, length=80, active=True)
        TechnicalType.objects.create(name='پرسلان نانو پولیش 10MIL')

        excel_file = self.create_excel_file([
            ["پرسلان نانو پوليش 10MIL مساحت 2.16 صاحارا 60*120 درجه1", 10, 21.6],
        ])
        self.client.post(reverse('import_upload'), {
            'factory': self.factory1.pk,
            'date': '1405/06/18',
            'file': excel_file,
        })
        batch = ProductionImportBatch.objects.filter(factory=self.factory1).first()
        row = batch.rows.first()

        # User manually edits size to 80x80 and sets notes
        row.size = s_custom
        row.edited_data = {'size': s_custom.pk, 'grade': self.g1.pk, 'area': '50.00', 'notes': 'اصلاح دستی'}
        row.save()

        # Trigger reprocess
        res = self.client.post(reverse('import_preview', args=[batch.token]), {
            'action': 'reprocess',
        })
        self.assertEqual(res.status_code, 302)

        row.refresh_from_db()
        # Size must remain the custom size (80x80)
        self.assertEqual(row.size, s_custom)
        # Conflict notice should be included in error_message
        self.assertIn("تعارض", row.error_message)

    def test_confirm_with_get_creates_no_productions(self):
        """GET request on import_confirm must be rejected and create zero records."""
        self.client.force_login(self.admin)
        batch = ProductionImportBatch.objects.create(
            factory=self.factory1,
            date=date(2026, 9, 9),
            uploaded_by=self.admin,
        )
        res = self.client.get(reverse('import_confirm', args=[batch.token]))
        self.assertEqual(res.status_code, 405)
        self.assertEqual(Production.objects.count(), 0)

    def test_cannot_confirm_batch_with_errors(self):
        """Incomplete or error rows prevent batch confirmation."""
        self.client.force_login(self.admin)
        batch = ProductionImportBatch.objects.create(
            factory=self.factory1,
            date=date(2026, 9, 9),
            uploaded_by=self.admin,
        )
        ProductionImportRow.objects.create(
            batch=batch,
            excel_row=2,
            raw_description="تست خطا",
            area=D('10.00'),
            status='error',
            error_message='سایز یافت نشد',
        )
        res = self.client.post(reverse('import_confirm', args=[batch.token]))
        self.assertEqual(res.status_code, 302)
        batch.refresh_from_db()
        self.assertNotEqual(batch.status, 'confirmed')
        self.assertEqual(Production.objects.count(), 0)

    def test_successful_confirm_links_rows_and_creates_audit(self):
        """Confirmed batch creates Production and Audit, links rows, and prevents double confirmation."""
        self.client.force_login(self.admin)
        s = Size.objects.create(width=60, length=120, active=True)
        tt = TechnicalType.objects.create(name='پرسلان نانو پولیش 10MIL')

        batch = ProductionImportBatch.objects.create(
            factory=self.factory1,
            date=date(2026, 9, 9),
            uploaded_by=self.admin,
            status='pending',
        )
        row = ProductionImportRow.objects.create(
            batch=batch,
            excel_row=2,
            raw_description="ردیف تأیید شده",
            size=s,
            grade=self.g1,
            technical_type=tt,
            area=D('100.00'),
            status='ok',
        )

        res = self.client.post(reverse('import_confirm', args=[batch.token]))
        self.assertEqual(res.status_code, 302)

        batch.refresh_from_db()
        self.assertEqual(batch.status, 'confirmed')
        self.assertIsNotNone(batch.confirmed_at)
        self.assertEqual(batch.confirmed_by, self.admin)

        row.refresh_from_db()
        self.assertIsNotNone(row.production)
        self.assertEqual(row.production.area, D('100.00'))
        self.assertEqual(Audit.objects.filter(production=row.production, action='create').count(), 1)

        # Attempt replay: second confirmation on already-confirmed batch
        prod_count = Production.objects.count()
        res2 = self.client.post(reverse('import_confirm', args=[batch.token]))
        self.assertEqual(res2.status_code, 302)
        self.assertEqual(Production.objects.count(), prod_count)  # No duplicate created!

    def test_unauthorized_factory_batch_access_prevented(self):
        """Entry user assigned to Factory 1 cannot view or confirm batch for Factory 2."""
        batch_f2 = ProductionImportBatch.objects.create(
            factory=self.factory2,
            date=date(2026, 9, 9),
            uploaded_by=self.admin,
        )
        self.client.force_login(self.entry_user)
        res_preview = self.client.get(reverse('import_preview', args=[batch_f2.token]))
        self.assertEqual(res_preview.status_code, 403)

        res_confirm = self.client.post(reverse('import_confirm', args=[batch_f2.token]))
        self.assertEqual(res_confirm.status_code, 403)

    def test_other_entry_user_batch_access_prevented(self):
        """Entry user cannot access another entry user's batch even with token."""
        other_entry = get_user_model().objects.create_user('other_entry', password='Pass-12345-Other!')
        p = Profile.objects.create(user=other_entry, role='entry')
        p.factories.add(self.factory1)

        batch = ProductionImportBatch.objects.create(
            factory=self.factory1,
            date=date(2026, 9, 9),
            uploaded_by=other_entry,
        )

        self.client.force_login(self.entry_user)
        res = self.client.get(reverse('import_preview', args=[batch.token]))
        self.assertEqual(res.status_code, 403)

    def test_formula_detection_in_essential_cells(self):
        """Excel cells with formulas in area/quantity/description must be flagged with error."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["شرح کالا", "جمع تولید", "متراژ"])
        ws.append(["پرسلان 60*120 درجه1", 100, "=B2*2.16"])
        out = BytesIO()
        wb.save(out)
        out.seek(0)
        
        file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scratch_test_formula.xlsx')
        with open(file_path, 'wb') as f:
            f.write(out.getvalue())
            
        try:
            rows = read_excel_import_file(file_path)
            self.assertEqual(len(rows), 1)
            self.assertIsNotNone(rows[0]['formula_error'])
            self.assertIn("حاوی فرمول است", rows[0]['formula_error'])
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
