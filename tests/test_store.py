import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from ssh_wallet.model import Forward, Host
from ssh_wallet.store import HostStore


class HostStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "ssh-wallet"
        self.path = self.dir / "hosts.json"
        self.store = HostStore(self.path)

    def test_missing_file_loads_as_empty(self):
        result = self.store.load()

        self.assertEqual(result.hosts, [])
        self.assertIsNone(result.backup_path)

    def test_saved_hosts_load_back_in_a_new_store(self):
        hosts = [
            Host(name="nas", host="10.0.0.5", port=2222, user="kuba",
                 key_path="~/.ssh/id_ed25519", note="Řádek 1\nŘádek 2", id="id-1"),
            Host(name="mikrotik", host="192.168.122.19", id="id-2"),
        ]

        self.store.save(hosts)
        result = HostStore(self.path).load()

        self.assertEqual(result.hosts, [
            Host(name="nas", host="10.0.0.5", port=2222, user="kuba",
                 key_path="~/.ssh/id_ed25519", note="Řádek 1\nŘádek 2", id="id-1"),
            Host(name="mikrotik", host="192.168.122.19", id="id-2"),
        ])
        self.assertIsNone(result.backup_path)

    def test_file_format(self):
        self.store.save([Host(name="m", host="h", id="id-1")])

        self.assertEqual(json.loads(self.path.read_text()), {
            "version": 2,
            "hosts": [{"id": "id-1", "name": "m", "host": "h", "port": 22,
                       "user": "", "key_path": "", "note": "", "jump_id": "", "forwards": []}],
        })

    def test_jump_and_forwards_load_back(self):
        hosts = [Host(name="pks2", host="2001:db8::1", id="id-2", jump_id="id-1",
                      forwards=[Forward("L", 5901, "localhost", 5901), Forward("R", 8080, "fe80::1", 80)])]

        self.store.save(hosts)

        self.assertEqual(HostStore(self.path).load().hosts, [
            Host(name="pks2", host="2001:db8::1", id="id-2", jump_id="id-1",
                 forwards=[Forward("L", 5901, "localhost", 5901), Forward("R", 8080, "fe80::1", 80)]),
        ])

    def test_file_from_before_jump_and_forwards_still_loads(self):
        self.dir.mkdir(parents=True)
        self.path.write_text('{"version": 1, "hosts": [{"id": "x", "name": "n", "host": "h", "port": 22,'
                             ' "user": "", "key_path": "", "note": ""}]}')

        result = self.store.load()

        self.assertEqual(result.hosts, [Host(name="n", host="h", id="x")])
        self.assertIsNone(result.backup_path)

    def test_hosts_keep_their_saved_order(self):
        self.store.save([Host(name="web", host="h", id="id-1"), Host(name="Alpha", host="h", id="id-2")])

        self.assertEqual([h.name for h in HostStore(self.path).load().hosts], ["web", "Alpha"])

    def test_version_1_file_loads_sorted_by_name(self):
        # Version 1 had no manual order; the app showed hosts sorted by name.
        self.dir.mkdir(parents=True)
        entries = [{"id": f"id-{name}", "name": name, "host": "h", "port": 22,
                    "user": "", "key_path": "", "note": ""} for name in ["web", "Alpha", "nas"]]
        self.path.write_text(json.dumps({"version": 1, "hosts": entries}))

        self.assertEqual([h.name for h in self.store.load().hosts], ["Alpha", "nas", "web"])

    def test_saved_file_is_private(self):
        self.store.save([Host(name="m", host="h")])

        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_save_leaves_only_the_hosts_file(self):
        self.store.save([Host(name="m", host="h")])
        self.store.save([Host(name="n", host="h")])

        self.assertEqual(os.listdir(self.dir), ["hosts.json"])

    def assert_backed_up(self, content: str):
        self.dir.mkdir(parents=True)
        self.path.write_text(content)

        result = self.store.load()

        self.assertEqual(result.hosts, [])
        self.assertIsNotNone(result.backup_path)
        self.assertEqual(result.backup_path.parent, self.dir)
        self.assertTrue(result.backup_path.name.startswith("hosts.json.bak-"))
        self.assertEqual(result.backup_path.read_text(), content)
        self.assertFalse(self.path.exists())

    def test_invalid_json_is_backed_up(self):
        self.assert_backed_up("{not json")

    def test_unknown_version_is_backed_up(self):
        self.assert_backed_up('{"version": 3, "hosts": []}')

    def test_entry_with_missing_field_is_backed_up(self):
        self.assert_backed_up('{"version": 1, "hosts": [{"id": "x", "name": "n"}]}')

    def test_entry_with_wrong_type_is_backed_up(self):
        self.assert_backed_up(
            '{"version": 1, "hosts": [{"id": "x", "name": "n", "host": "h", "port": "22",'
            ' "user": "", "key_path": "", "note": ""}]}'
        )

    def test_forward_with_wrong_type_is_backed_up(self):
        self.assert_backed_up(
            '{"version": 1, "hosts": [{"id": "x", "name": "n", "host": "h", "port": 22,'
            ' "user": "", "key_path": "", "note": "",'
            ' "forwards": [{"kind": "L", "port": "5901", "dest_host": "localhost", "dest_port": 5901}]}]}'
        )


if __name__ == "__main__":
    unittest.main()
