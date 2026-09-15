from decimal import Decimal
from django.test import SimpleTestCase
from production.templatetags.fa import num, rounded_num


class ReportDisplayRoundingTests(SimpleTestCase):
    def test_rounding_boundaries_and_missing_values(self):
        cases = [('79.58', '۸۰'), ('79.49', '۷۹'), ('78.50', '۷۹'),
                 ('21487.50', '۲۱٬۴۸۸'), ('0.00', '۰'), (None, '—')]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(rounded_num(value), expected)

    def test_original_precision_is_preserved(self):
        value = Decimal('21487.50')
        self.assertEqual(rounded_num(value), '۲۱٬۴۸۸')
        self.assertEqual(value, Decimal('21487.50'))
        self.assertEqual(num(value), '۲۱٬۴۸۷٫۵۰')
