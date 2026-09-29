import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_public import findings, private_path, allowed_email


class PublicAuditTests(unittest.TestCase):
    def test_redacts_secrets_in_findings(self):
        secret = "ghp_" + "a" * 36
        result = findings(secret.encode(), "sample")
        self.assertEqual(result[0]["rule"], "github-token")
        self.assertNotIn(secret, str(result))

    def test_blocks_data_files_and_personal_email(self):
        self.assertTrue(private_path("nested/prices.xlsx"))
        self.assertTrue(private_path("catalog.local.json"))
        self.assertFalse(private_path("catalog_tool/catalog.py"))
        self.assertTrue(allowed_email("123+example@users.noreply.github.com"))
        address = "private" + "@" + "mail.test"
        self.assertEqual(findings(address.encode(), "sample")[0]["rule"], "personal-email")


if __name__ == "__main__":
    unittest.main()
