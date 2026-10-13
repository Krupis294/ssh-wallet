import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import gi

gi.require_version("Pango", "1.0")
from gi.repository import Pango  # noqa: E402

from ssh_wallet.launcher import LaunchError  # noqa: E402
from ssh_wallet.model import Host  # noqa: E402
from ssh_wallet.rofi import (  # noqa: E402
    GUI_ENTRY, THEME_PATH, Row, encode, host_rows, parse_selection, rofi_command, run,
)
from ssh_wallet.store import HostStore  # noqa: E402
from ssh_wallet.wallet import Wallet  # noqa: E402
from tests.fakes import FakeVault  # noqa: E402
from tests.test_wallet import RecordingLaunch  # noqa: E402


def visible_text(markup: str) -> str:
    """What rofi renders for a markup row; fails on invalid markup."""
    _ok, _attrs, text, _accel = Pango.parse_markup(markup, -1, "\0")
    return text


def done(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class HostRowsTest(unittest.TestCase):
    def test_search_text_is_plain_and_includes_note(self):
        [row] = host_rows([Host(name="nas", host="10.0.0.6", user="kuba", note="Záloha\nfotek")],
                          has_password=lambda _id: False)

        self.assertEqual(row.search, "nas kuba@10.0.0.6:22 Záloha fotek")

    def test_display_shows_aligned_names_address_and_tags(self):
        hosts = [Host(name="nas", host="10.0.0.6", user="kuba", id="a"),
                 Host(name="mikrotik", host="192.168.122.19", user="admin",
                      key_path="~/.ssh/k", id="b")]

        rows = host_rows(hosts, has_password=lambda host_id: host_id == "b")

        self.assertEqual([visible_text(r.display) for r in rows], [
            "nas       kuba@10.0.0.6:22",
            "mikrotik  admin@192.168.122.19:22  Heslo Klíč",
        ])

    def test_markup_in_names_is_escaped(self):
        [row] = host_rows([Host(name="a<b>&c", host="h")], has_password=lambda _id: False)

        self.assertEqual(visible_text(row.display), "a<b>&c  h:22")


class EncodeTest(unittest.TestCase):
    def test_rows_use_display_and_permanent_options(self):
        rows = [Row("nas h:22", "nas  <span>h:22</span>"), Row("open", "<i>open</i>", permanent=True)]

        self.assertEqual(
            encode(rows),
            "nas h:22\0display\x1fnas  <span>h:22</span>\n"
            "open\0display\x1f<i>open</i>\x1fpermanent\x1ftrue\n",
        )

    def test_control_characters_cannot_break_the_row_format(self):
        text = encode([Row("a\nb\0c\x1fd", "x\ny")])

        self.assertEqual(text.count("\n"), 1)
        self.assertEqual(text.count("\0"), 1)
        self.assertEqual(text.count("\x1f"), 1)


class RofiCommandTest(unittest.TestCase):
    def test_own_theme(self):
        self.assertEqual(rofi_command(Path("/t.rasi")), [
            "rofi", "-dmenu", "-i", "-markup-rows", "-no-custom", "-format", "i",
            "-p", "SSH", "-theme", "/t.rasi",
        ])

    def test_system_theme_passes_no_theme(self):
        self.assertNotIn("-theme", rofi_command(None))

    def test_message(self):
        self.assertEqual(rofi_command(None, mesg="ahoj")[-2:], ["-mesg", "ahoj"])


class ParseSelectionTest(unittest.TestCase):
    def test_cases(self):
        for result, expected in [(done("1\n"), 1), (done("0\n"), 0), (done("", 1), None),
                                 (done(""), None), (done("x\n"), None)]:
            with self.subTest(stdout=result.stdout, code=result.returncode):
                self.assertEqual(parse_selection(result), expected)


class FakeRofi:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, argv, text):
        self.calls.append((argv, text))
        return self.results.pop(0)


class RunTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "hosts.json"
        self.launch = RecordingLaunch()
        self.gui_opened = []

    def run_with(self, rofi, hosts=()):
        if hosts:
            seed = Wallet(HostStore(self.path), FakeVault(), launch=self.launch)
            seed.load()
            for host in hosts:
                seed.save_host(host)
        wallet = Wallet(HostStore(self.path), FakeVault(), launch=self.launch)
        return run(wallet, rofi, theme=None, open_gui=lambda: self.gui_opened.append(True))

    def test_selected_host_is_connected(self):
        rofi = FakeRofi(done("1\n"))

        code = self.run_with(rofi, [Host(name="web", host="10.0.0.5"), Host(name="nas", host="10.0.0.6")])

        self.assertEqual(code, 0)
        [command] = self.launch.commands
        self.assertEqual(command.argv[-1], "10.0.0.5")  # sorted: nas, web

    def test_last_entry_opens_gui(self):
        rofi = FakeRofi(done("1\n"))

        self.run_with(rofi, [Host(name="nas", host="10.0.0.6")])

        self.assertEqual(self.gui_opened, [True])
        self.assertEqual(self.launch.commands, [])
        self.assertTrue(rofi.calls[0][1].endswith(f"{GUI_ENTRY}\0display\x1f<i>{GUI_ENTRY}</i>"
                                                  "\x1fpermanent\x1ftrue\n"))

    def test_cancel_does_nothing(self):
        code = self.run_with(FakeRofi(done("", 1)), [Host(name="nas", host="h")])

        self.assertEqual((code, self.launch.commands, self.gui_opened), (0, [], []))

    def test_empty_wallet_shows_hint_and_only_gui_entry(self):
        rofi = FakeRofi(done("", 1))

        self.run_with(rofi)

        argv, text = rofi.calls[0]
        self.assertIn("Zatím žádné hosty", argv[argv.index("-mesg") + 1])
        self.assertEqual(text.count("\n"), 1)

    def test_broken_hosts_file_is_reported(self):
        self.path.write_text("{broken")
        rofi = FakeRofi(done("", 1))

        self.run_with(rofi)

        argv, _ = rofi.calls[0]
        self.assertIn("hosts.json.bak-", argv[argv.index("-mesg") + 1])

    def test_launch_failure_is_shown_in_rofi(self):
        def failing_launch(command):
            raise LaunchError("Nepodařilo se spustit kitty: No such file")

        self.launch = failing_launch
        rofi = FakeRofi(done("0\n"), done())

        code = self.run_with(rofi, [Host(name="nas", host="h")])

        self.assertEqual(code, 1)
        self.assertEqual(rofi.calls[1][0], ["rofi", "-e", "Nepodařilo se spustit kitty: No such file"])


@unittest.skipUnless(shutil.which("rofi"), "rofi not installed")
class ThemeFileTest(unittest.TestCase):
    def test_theme_parses(self):
        result = subprocess.run(["rofi", "-dump-theme", "-theme", str(THEME_PATH)],
                                capture_output=True, text=True, timeout=10)

        # rofi exits 0 even for a broken theme; it only warns and falls back to defaults.
        self.assertNotIn("Failed to parse", result.stderr)
        self.assertIn("rgba ( 135, 213, 162, 100 % )", result.stdout)  # accent #87d5a2


if __name__ == "__main__":
    unittest.main()
