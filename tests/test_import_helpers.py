import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMPORT_PATH = PROJECT_ROOT / "import.py"


spec = importlib.util.spec_from_file_location("expense_import", IMPORT_PATH)
expense_import = importlib.util.module_from_spec(spec)
spec.loader.exec_module(expense_import)


class ImportHelperTests(unittest.TestCase):
    def test_parse_money_accepts_common_statement_formats(self):
        self.assertEqual(expense_import.parse_money("1,234.56"), 1234.56)
        self.assertEqual(expense_import.parse_money("$42.10"), 42.10)
        self.assertEqual(expense_import.parse_money("(18.99)"), -18.99)

    def test_clean_name_normalizes_pos_prefixes_and_locations(self):
        self.assertEqual(
            expense_import.clean_name("TST* GOLDHILL BISTRO San Jose CA"),
            "Goldhill Bistro",
        )
        self.assertEqual(expense_import.clean_name("AMZN Mktp US*2X3"), "Amazon")

    def test_parse_per_card_handles_currency_and_skips_payments(self):
        rows = [
            {
                "Transaction Date": "04/01/2026",
                "Post Date": "04/02/2026",
                "Description": "SAFEWAY SAN JOSE CA",
                "Category": "Groceries",
                "Type": "Sale",
                "Amount": "-$1,234.56",
                "Memo": "",
            },
            {
                "Transaction Date": "04/03/2026",
                "Post Date": "04/03/2026",
                "Description": "AUTOPAY PAYMENT",
                "Category": "",
                "Type": "Payment",
                "Amount": "1234.56",
                "Memo": "",
            },
        ]
        parsed, skipped = expense_import._parse_per_card(iter(rows))

        self.assertEqual(skipped, 1)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["amount"], 1234.56)


if __name__ == "__main__":
    unittest.main()
