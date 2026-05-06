import tempfile
import unittest
from datetime import date
from pathlib import Path

from reader.report import aggregate, default_output_path, render_pdf


class ReportTests(unittest.TestCase):
    def test_aggregate_ignores_refunds_and_sorts_totals(self):
        rows = [
            {"amount": 40, "name": "Cafe", "category": "Dining", "subcategory": "Nonessential"},
            {"amount": 20, "name": "Safeway", "category": "Grocery", "subcategory": "Essential"},
            {"amount": -20, "name": "Safeway", "category": "Grocery", "subcategory": "Essential"},
            {"amount": 10, "name": "Cafe", "category": "Dining", "subcategory": "Nonessential"},
        ]

        stats = aggregate(rows)

        self.assertEqual(stats["total"], 70)
        self.assertEqual(stats["n_purchases"], 3)
        self.assertEqual(stats["categories"][0], ("Dining", 50.0))
        self.assertEqual(stats["top_merchants"][0], ("Cafe", 50.0))

    def test_render_pdf_writes_nonempty_file(self):
        stats = {
            "total": 70,
            "n_purchases": 3,
            "categories": [("Dining", 50), ("Grocery", 20)],
            "subcategories": [("Nonessential", 50), ("Essential", 20)],
            "top_merchants": [("Cafe", 50), ("Safeway", 20)],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.pdf"
            render_pdf(stats, date(2026, 4, 1), date(2026, 4, 30), output)

            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1000)

    def test_default_output_path_uses_report_directory(self):
        self.assertEqual(default_output_path("2026-01"), Path("report") / "expense-report-2026-01.pdf")


if __name__ == "__main__":
    unittest.main()
