import unittest
from io import BytesIO

from openpyxl import Workbook

from app.jood_whatsapp_import import parse_contact_upload


class JoodWhatsAppImportTests(unittest.TestCase):
    def test_csv_with_arabic_headers_normalizes_and_deduplicates(self):
        body = (
            "رقم الجوال,الاسم,اسم النشاط,المدينة,ملاحظات\n"
            "0501234567,سارة,مركز سارة,الرياض,مهتمة\n"
            "+966501234567,سارة مكرر,مكرر,الرياض,يتجاوز\n"
            "0557654321,محمد,مطعم محمد,الرياض,\n"
        ).encode("utf-8")
        rows = parse_contact_upload("contacts.csv", body, "merchant")
        self.assertEqual([row.phone for row in rows], ["966501234567", "966557654321"])
        self.assertEqual(rows[0].display_name, "سارة")
        self.assertEqual(rows[0].business_name, "مركز سارة")
        self.assertEqual(rows[0].contact_type, "merchant")

    def test_csv_without_header_uses_documented_column_order(self):
        rows = parse_contact_upload(
            "contacts.csv",
            "0501234567,سارة,مركز سارة,الرياض,ملاحظة".encode("utf-8"),
            "customer",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].phone, "966501234567")
        self.assertEqual(rows[0].notes, "ملاحظة")

    def test_rejects_unsupported_or_empty_upload(self):
        with self.assertRaisesRegex(ValueError, "CSV or XLSX"):
            parse_contact_upload("contacts.txt", b"0501234567", "customer")
        with self.assertRaisesRegex(ValueError, "no valid"):
            parse_contact_upload("contacts.csv", b"bad-number", "customer")

    def test_xlsx_upload_reads_real_workbook(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["رقم الجوال", "الاسم", "اسم النشاط", "المدينة"])
        sheet.append(["0501234567", "سارة", "مركز سارة", "الرياض"])
        output = BytesIO()
        workbook.save(output)
        rows = parse_contact_upload("contacts.xlsx", output.getvalue(), "merchant")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].phone, "966501234567")
        self.assertEqual(rows[0].business_name, "مركز سارة")


if __name__ == "__main__":
    unittest.main()
