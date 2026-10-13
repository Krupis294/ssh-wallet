import tempfile
import unittest
from pathlib import Path

from ssh_wallet.launcher import LaunchError
from ssh_wallet.model import Forward, Host
from ssh_wallet.store import HostStore
from ssh_wallet.wallet import Wallet, WalletError
from tests.fakes import FakeVault

ASKPASS = Path("/opt/wallet/bin/ssh-wallet-askpass")


class RecordingLaunch:
    def __init__(self):
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)


class WalletTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "cfg"
        self.store = HostStore(self.dir / "hosts.json")
        self.vault = FakeVault()
        self.launch = RecordingLaunch()
        self.wallet = self.new_wallet()

    def new_wallet(self, vault=None) -> Wallet:
        wallet = Wallet(self.store, vault or self.vault, launch=self.launch, askpass_path=ASKPASS)
        wallet.load()
        return wallet

    def names_on_disk(self) -> list[str]:
        return [h.name for h in self.store.load().hosts]

    def make_dir_read_only(self):
        self.dir.chmod(0o500)
        self.addCleanup(self.dir.chmod, 0o700)

    def test_hosts_are_sorted_by_name_ignoring_case(self):
        for name in ["beta", "Alpha", "gamma"]:
            self.wallet.save_host(Host(name=name, host="h"))

        self.assertEqual([h.name for h in self.wallet.hosts], ["Alpha", "beta", "gamma"])

    def test_saved_host_survives_reload(self):
        self.wallet.save_host(Host(name="nas", host="10.0.0.5", id="id-1"))

        self.assertEqual(self.new_wallet().hosts, [Host(name="nas", host="10.0.0.5", id="id-1")])

    def test_saving_existing_host_replaces_it(self):
        self.wallet.save_host(Host(name="nas", host="10.0.0.5", id="id-1"))

        self.wallet.save_host(Host(name="nas2", host="10.0.0.6", id="id-1"))

        self.assertEqual(self.names_on_disk(), ["nas2"])

    def test_password_goes_to_vault_not_to_file(self):
        self.wallet.save_host(Host(name="nas", host="h", id="id-1"), password="s3cret")

        self.assertEqual(self.vault.passwords, {"id-1": "s3cret"})
        self.assertEqual(self.vault.labels, {"id-1": "SSH Wallet: nas"})
        self.assertNotIn("s3cret", (self.dir / "hosts.json").read_text())
        self.assertTrue(self.wallet.has_password("id-1"))

    def test_saving_without_password_keeps_stored_one(self):
        self.wallet.save_host(Host(name="nas", host="h", id="id-1"), password="s3cret")

        self.wallet.save_host(Host(name="nas", host="h2", id="id-1"))

        self.assertEqual(self.vault.passwords, {"id-1": "s3cret"})

    def test_remove_password(self):
        self.wallet.save_host(Host(name="nas", host="h", id="id-1"), password="s3cret")

        self.wallet.save_host(Host(name="nas", host="h", id="id-1"), remove_password=True)

        self.assertEqual(self.vault.passwords, {})
        self.assertFalse(self.wallet.has_password("id-1"))

    def test_keyring_failure_leaves_hosts_untouched(self):
        self.wallet.save_host(Host(name="old", host="h", id="id-1"))
        wallet = self.new_wallet(vault=FakeVault(fail=True))

        with self.assertRaises(WalletError):
            wallet.save_host(Host(name="new", host="h", id="id-1"), password="pw")

        self.assertEqual(self.names_on_disk(), ["old"])
        self.assertEqual([h.name for h in wallet.hosts], ["old"])

    def test_file_write_failure_leaves_memory_untouched(self):
        self.wallet.save_host(Host(name="old", host="h", id="id-1"))
        self.make_dir_read_only()

        with self.assertRaises(WalletError):
            self.wallet.save_host(Host(name="new", host="h"))

        self.assertEqual([h.name for h in self.wallet.hosts], ["old"])

    def test_invalid_host_is_rejected(self):
        with self.assertRaises(WalletError) as ctx:
            self.wallet.save_host(Host(name="", host="h"))

        self.assertIn("Název nesmí být prázdný.", str(ctx.exception))
        self.assertEqual(self.names_on_disk(), [])

    def test_delete_removes_host_and_password(self):
        self.wallet.save_host(Host(name="a", host="h", id="id-1"), password="pw")
        self.wallet.save_host(Host(name="b", host="h", id="id-2"))

        self.wallet.delete_host("id-1")

        self.assertEqual(self.names_on_disk(), ["b"])
        self.assertEqual([h.name for h in self.wallet.hosts], ["b"])
        self.assertEqual(self.vault.passwords, {})

    def test_delete_with_broken_keyring_still_removes_host(self):
        self.wallet.save_host(Host(name="a", host="h", id="id-1"))
        wallet = self.new_wallet(vault=FakeVault(fail=True))

        with self.assertRaises(WalletError) as ctx:
            wallet.delete_host("id-1")

        self.assertIn("keyring", str(ctx.exception))
        self.assertEqual(self.names_on_disk(), [])

    def test_has_password_is_false_when_keyring_fails(self):
        self.assertFalse(self.new_wallet(vault=FakeVault(fail=True)).has_password("id-1"))

    def test_load_reports_backup_of_broken_file(self):
        self.dir.mkdir()
        (self.dir / "hosts.json").write_text("{broken")

        backup = Wallet(self.store, self.vault, launch=self.launch).load()

        self.assertEqual(backup.read_text(), "{broken")

    def test_connect_with_password_uses_askpass(self):
        host = Host(name="nas", host="10.0.0.5", user="kuba", id="id-1")
        self.wallet.save_host(host, password="pw")

        self.wallet.connect(host)

        [command] = self.launch.commands
        self.assertEqual(command.argv[-1], "kuba@10.0.0.5")
        self.assertEqual(command.env["SSH_WALLET_ID"], "id-1")
        self.assertEqual(command.env["SSH_ASKPASS"], str(ASKPASS))

    def test_connect_without_password_has_no_askpass(self):
        host = Host(name="nas", host="10.0.0.5", id="id-1")
        self.wallet.save_host(host)

        self.wallet.connect(host)

        self.assertEqual(self.launch.commands[0].env, {})


    def test_connect_goes_through_the_jump_host(self):
        self.wallet.save_host(Host(name="bastion", host="bastion.example", user="admin", id="id-j"),
                              password="jump-pw")
        target = Host(name="pks2", host="10.0.0.6", user="student", id="id-t", jump_id="id-j")
        self.wallet.save_host(target)

        self.wallet.connect(target)

        [command] = self.launch.commands
        self.assertIn("ProxyCommand=ssh -W '[%h]:%p' -p 22 -- admin@bastion.example", command.argv)
        self.assertEqual(command.env["SSH_WALLET_JUMP_ID"], "id-j")

    def test_connect_with_a_deleted_jump_host_fails_clearly(self):
        target = Host(name="pks2", host="10.0.0.6", id="id-t", jump_id="gone")
        self.wallet.save_host(target)

        with self.assertRaises(LaunchError) as ctx:
            self.wallet.connect(target)

        self.assertEqual(str(ctx.exception), "Jump server hostu pks2 už neexistuje. Vyber jiný v úpravách.")
        self.assertEqual(self.launch.commands, [])

    def test_tunnel_command_uses_forwards_and_jump(self):
        self.wallet.save_host(Host(name="bastion", host="bastion.example", id="id-j"))
        target = Host(name="pks2", host="10.0.0.6", id="id-t", jump_id="id-j",
                      forwards=[Forward("L", 5901, "localhost", 5901)])
        self.wallet.save_host(target, password="pw")

        command = self.wallet.tunnel_command(target)

        self.assertEqual(command.argv[command.argv.index("-L") + 1], "5901:localhost:5901")
        self.assertIn("-N", command.argv)
        self.assertIn("ProxyCommand=ssh -W '[%h]:%p' -p 22 -- bastion.example", command.argv)
        self.assertEqual(command.env["SSH_WALLET_ID"], "id-t")

    def test_jump_candidates_are_the_other_hosts(self):
        for name, host_id in [("b", "id-b"), ("A", "id-a"), ("self", "id-s")]:
            self.wallet.save_host(Host(name=name, host="h", id=host_id))

        self.assertEqual([h.name for h in self.wallet.jump_candidates("id-s")], ["A", "b"])
        self.assertEqual([h.name for h in self.wallet.jump_candidates(None)], ["A", "b", "self"])


if __name__ == "__main__":
    unittest.main()
