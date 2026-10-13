"""Smoke tests of the GTK widgets. They need a display, so they skip without one."""

import tempfile
import unittest
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ssh_wallet.model import Host  # noqa: E402
from ssh_wallet.store import HostStore  # noqa: E402
from ssh_wallet.wallet import Wallet  # noqa: E402
from tests.fakes import FakeVault  # noqa: E402
from tests.test_wallet import RecordingLaunch  # noqa: E402

HAS_DISPLAY = Gtk.init_check()
if HAS_DISPLAY:
    Adw.init()


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class MainWindowTest(unittest.TestCase):
    def setUp(self):
        from ssh_wallet.ui.window import MainWindow

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.launch = RecordingLaunch()
        self.wallet = Wallet(HostStore(Path(tmp.name) / "hosts.json"), FakeVault(), launch=self.launch)
        self.wallet.load()
        self.make_window = lambda: MainWindow(wallet=self.wallet)

    def test_empty_wallet_shows_empty_state(self):
        window = self.make_window()

        self.assertEqual(window.stack.get_visible_child_name(), "empty")

    def test_hosts_are_listed_sorted(self):
        self.wallet.save_host(Host(name="web", host="10.0.0.5"))
        self.wallet.save_host(Host(name="nas", host="10.0.0.6"))

        window = self.make_window()

        self.assertEqual(window.stack.get_visible_child_name(), "list")
        self.assertEqual([h.name for h in window.visible_hosts()], ["nas", "web"])

    def test_search_filters_and_reports_no_results(self):
        self.wallet.save_host(Host(name="web", host="10.0.0.5"))
        self.wallet.save_host(Host(name="nas", host="10.0.0.6"))
        window = self.make_window()

        window.search_entry.set_text("web")
        self.assertEqual([h.name for h in window.visible_hosts()], ["web"])

        window.search_entry.set_text("zzz")
        self.assertEqual(window.stack.get_visible_child_name(), "no-results")

    def test_enter_in_search_connects_to_first_match(self):
        self.wallet.save_host(Host(name="web", host="10.0.0.5"))
        self.wallet.save_host(Host(name="nas", host="10.0.0.6", user="kuba"))
        window = self.make_window()

        window.search_entry.set_text("10.0")
        window.search_entry.emit("activate")

        [command] = self.launch.commands
        self.assertEqual(command.argv[-1], "kuba@10.0.0.6")

    def test_enter_connects_to_selected_row_when_it_is_visible(self):
        self.wallet.save_host(Host(name="web", host="10.0.0.5"))
        self.wallet.save_host(Host(name="nas", host="10.0.0.6"))
        window = self.make_window()

        window.select_next(1)
        window.search_entry.emit("activate")

        self.assertEqual(self.launch.commands[0].argv[-1], "10.0.0.5")


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class HostDialogTest(unittest.TestCase):
    def setUp(self):
        self.saved = []
        # Dialogs must be presented to close; an unmapped parent keeps them off screen.
        self.parent = Adw.ApplicationWindow()

    def make_dialog(self, host, has_password):
        from ssh_wallet.ui.host_dialog import HostDialog

        dialog = HostDialog(host, has_password=has_password, on_save=self.on_save)
        dialog.present(self.parent)
        return dialog

    def on_save(self, host, password, remove_password):
        self.saved.append((host, password, remove_password))
        return None

    def test_save_is_disabled_until_name_and_host_are_filled(self):
        dialog = self.make_dialog(None, has_password=False)
        self.assertFalse(dialog.save_button.get_sensitive())

        dialog.name_row.set_text("nas")
        dialog.host_row.set_text("10.0.0.6")
        self.assertTrue(dialog.save_button.get_sensitive())

    def test_saving_new_host_passes_fields_and_password(self):
        dialog = self.make_dialog(None, has_password=False)
        dialog.name_row.set_text("nas")
        dialog.host_row.set_text("10.0.0.6")
        dialog.port_row.set_value(2222)
        dialog.user_row.set_text("kuba")
        dialog.password_row.set_text("s3cret")
        dialog.note_view.get_buffer().set_text("Poznámka")

        dialog.save_button.emit("clicked")

        [(host, password, remove)] = self.saved
        self.assertEqual((host.name, host.host, host.port, host.user, host.note),
                         ("nas", "10.0.0.6", 2222, "kuba", "Poznámka"))
        self.assertEqual((password, remove), ("s3cret", False))

    def test_editing_keeps_id_and_empty_password_means_keep(self):
        original = Host(name="nas", host="10.0.0.6", key_path="~/.ssh/k", id="id-1")
        dialog = self.make_dialog(original, has_password=True)

        dialog.save_button.emit("clicked")

        [(host, password, remove)] = self.saved
        self.assertEqual(host, original)
        self.assertEqual((password, remove), (None, False))

    def test_remove_password_switch(self):
        dialog = self.make_dialog(Host(name="n", host="h", id="id-1"), has_password=True)
        dialog.remove_password_row.set_active(True)

        dialog.save_button.emit("clicked")

        self.assertEqual(self.saved[0][2], True)



def find_widgets(widget, predicate) -> list:
    found = []
    if predicate(widget):
        found.append(widget)
    child = widget.get_first_child()
    while child is not None:
        found += find_widgets(child, predicate)
        child = child.get_next_sibling()
    return found


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class StyleTest(unittest.TestCase):
    def test_stylesheet_parses_without_errors(self):
        from ssh_wallet.ui.style import STYLE_PATH

        provider = Gtk.CssProvider()
        errors = []
        provider.connect("parsing-error", lambda _p, section, error:
                         errors.append(f"{section.to_string()}: {error.message}"))
        provider.load_from_path(str(STYLE_PATH))

        self.assertEqual(errors, [])


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class HostRowTest(unittest.TestCase):
    def make_row(self, host, has_password=False):
        from ssh_wallet.ui.window import HostRow

        self.edited, self.connected = [], []
        return HostRow(host, has_password, on_edit=self.edited.append, on_connect=self.connected.append)

    def badges(self, row) -> list[str]:
        return [w.get_label() for w in find_widgets(
            row, lambda w: isinstance(w, Gtk.Label) and w.has_css_class("badge"))]

    def button(self, row, label):
        [button] = find_widgets(row, lambda w: isinstance(w, Gtk.Button) and w.get_label() == label)
        return button

    def test_badges_for_password_and_key(self):
        row = self.make_row(Host(name="n", host="h", key_path="~/.ssh/k"), has_password=True)

        self.assertEqual(self.badges(row), ["Heslo", "Klíč"])

    def test_plain_host_has_no_badges(self):
        self.assertEqual(self.badges(self.make_row(Host(name="n", host="h"))), [])

    def test_row_buttons_edit_and_connect_their_host(self):
        host = Host(name="n", host="h")
        row = self.make_row(host)

        self.button(row, "Upravit").emit("clicked")
        self.button(row, "Připojit").emit("clicked")

        self.assertEqual((self.edited, self.connected), ([host], [host]))


if __name__ == "__main__":
    unittest.main()
