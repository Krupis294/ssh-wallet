"""Integration tests against the real Secret Service (gnome-keyring).

They touch the user's keyring, so they only run with SSH_WALLET_KEYRING_TESTS=1.
Items are stored under a separate test schema and removed afterwards.
"""

import os
import unittest
import uuid

TEST_SCHEMA = "io.github.krupis294.SshWallet.Test"


@unittest.skipUnless(os.environ.get("SSH_WALLET_KEYRING_TESTS") == "1",
                     "set SSH_WALLET_KEYRING_TESTS=1 to run keyring tests")
class SecretVaultTest(unittest.TestCase):
    def setUp(self):
        from ssh_wallet.vault import SecretVault

        self.vault = SecretVault(schema_name=TEST_SCHEMA)
        self.entry = f"test-{uuid.uuid4()}"
        self.addCleanup(self.vault.delete, self.entry)

    def test_unknown_entry_has_no_password(self):
        self.assertIsNone(self.vault.get(self.entry))
        self.assertFalse(self.vault.has(self.entry))

    def test_stored_password_can_be_read_back(self):
        self.vault.set(self.entry, "tajné heslo ' \" $x", label="test")

        self.assertEqual(self.vault.get(self.entry), "tajné heslo ' \" $x")
        self.assertTrue(self.vault.has(self.entry))

    def test_set_replaces_previous_password(self):
        self.vault.set(self.entry, "first", label="test")
        self.vault.set(self.entry, "second", label="test")

        self.assertEqual(self.vault.get(self.entry), "second")

    def test_delete_removes_password(self):
        self.vault.set(self.entry, "pw", label="test")

        self.vault.delete(self.entry)

        self.assertIsNone(self.vault.get(self.entry))

    def test_delete_of_unknown_entry_is_not_an_error(self):
        self.vault.delete(self.entry)

    def test_entries_are_isolated_by_schema(self):
        from ssh_wallet.vault import SecretVault

        self.vault.set(self.entry, "pw", label="test")

        self.assertIsNone(SecretVault(schema_name=TEST_SCHEMA + ".Other").get(self.entry))


if __name__ == "__main__":
    unittest.main()
