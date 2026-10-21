"""Smoke tests of the GTK widgets. They need a display, so they skip without one."""

import tempfile
import unittest
import warnings
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ssh_wallet.model import Forward, Host  # noqa: E402
from ssh_wallet.store import HostStore  # noqa: E402
from ssh_wallet.ui.host_dialog import HostDialog  # noqa: E402
from ssh_wallet.wallet import Wallet  # noqa: E402
from tests.fakes import FakeVault  # noqa: E402
from tests.test_tunnel import FakeSpawner  # noqa: E402
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

    def test_hosts_are_listed_in_saved_order(self):
        self.wallet.save_host(Host(name="web", host="10.0.0.5"))
        self.wallet.save_host(Host(name="nas", host="10.0.0.6"))

        window = self.make_window()

        self.assertEqual(window.stack.get_visible_child_name(), "list")
        self.assertEqual([h.name for h in window.visible_hosts()], ["web", "nas"])

    def test_search_filters_and_reports_no_results(self):
        self.wallet.save_host(Host(name="web", host="10.0.0.5"))
        self.wallet.save_host(Host(name="nas", host="10.0.0.6"))
        window = self.make_window()

        window.search_entry.set_text("web")
        self.assertEqual([h.name for h in window.visible_hosts()], ["web"])

        window.search_entry.set_text("zzz")
        self.assertEqual(window.stack.get_visible_child_name(), "no-results")

    def test_enter_in_search_connects_to_first_match(self):
        self.wallet.save_host(Host(name="nas", host="10.0.0.6", user="kuba"))
        self.wallet.save_host(Host(name="web", host="10.0.0.5"))
        window = self.make_window()

        window.search_entry.set_text("10.0")
        window.search_entry.emit("activate")

        [command] = self.launch.commands
        self.assertEqual(command.argv[-1], "kuba@10.0.0.6")

    def test_enter_connects_to_selected_row_when_it_is_visible(self):
        self.wallet.save_host(Host(name="nas", host="10.0.0.6"))
        self.wallet.save_host(Host(name="web", host="10.0.0.5"))
        window = self.make_window()

        window.select_next(1)
        window.search_entry.emit("activate")

        self.assertEqual(self.launch.commands[0].argv[-1], "10.0.0.5")


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class HostActionsTest(unittest.TestCase):
    """Context menu actions; they act on the selected row."""

    def setUp(self):
        from ssh_wallet.ui.window import MainWindow

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.launch = RecordingLaunch()
        self.vault = FakeVault()
        self.wallet = Wallet(HostStore(Path(tmp.name) / "hosts.json"), self.vault, launch=self.launch)
        self.wallet.load()
        for name in ["a", "b", "c"]:
            self.wallet.save_host(Host(name=name, host=f"{name}.example", id=f"id-{name}"))
        self.window = MainWindow(wallet=self.wallet)

    def select(self, name):
        [row] = [r for r in self.window._rows if r.host.name == name]
        self.window.listbox.select_row(row)

    def run_action(self, name):
        self.assertTrue(self.window.activate_action(f"win.{name}", None))

    def names(self):
        return [h.name for h in self.window.visible_hosts()]

    def selected(self):
        return self.window.listbox.get_selected_row().host.name

    def test_every_menu_item_is_a_window_action(self):
        from ssh_wallet.ui.window import host_menu

        actions = []
        sections = host_menu()
        for i in range(sections.get_n_items()):
            section = sections.get_item_link(i, "section")
            for j in range(section.get_n_items()):
                actions.append(section.get_item_attribute_value(j, "action").get_string())

        self.assertEqual(len(actions), 5)
        self.assertNotIn("win.move-up", actions)
        for action in actions:
            self.assertIsNotNone(self.window.lookup_action(action.removeprefix("win.")), action)

    def test_menu_hides_the_shortcuts_of_its_items(self):
        # The menu is narrow; "Kopírovat ssh příkaz" ran into its "Shift+Ctrl+C".
        from ssh_wallet.ui.window import host_menu

        sections = host_menu()
        for i in range(sections.get_n_items()):
            section = sections.get_item_link(i, "section")
            for j in range(section.get_n_items()):
                self.assertEqual(section.get_item_attribute_value(j, "accel").get_string(), "")

    def test_menu_opens_at_the_pointer_and_selects_the_row(self):
        [row] = [r for r in self.window._rows if r.host.name == "b"]

        self.window._open_menu(row, 120.7, 95.2)

        menu = self.window.listbox.get_last_child()
        self.assertIsInstance(menu, Gtk.PopoverMenu)
        ok, rect = menu.get_pointing_to()
        self.assertEqual((ok, rect.x, rect.y), (True, 120, 95))
        self.assertEqual(self.selected(), "b")
        menu.popdown()
        menu.unparent()

    def test_connect(self):
        self.select("b")

        self.run_action("connect-host")

        self.assertEqual(self.launch.commands[0].argv[-1], "b.example")

    def test_copy_puts_the_ssh_command_on_the_clipboard(self):
        self.select("b")

        self.run_action("copy-command")

        result = []
        with warnings.catch_warnings():
            # PyGObject's asyncio glue warns about deprecated policy APIs on Python 3.14.
            warnings.simplefilter("ignore", DeprecationWarning)
            self.window.get_clipboard().read_text_async(None, lambda c, r: result.append(c.read_text_finish(r)))
            context = GLib.MainContext.default()
            for _ in range(100):
                if result:
                    break
                context.iteration(False)
        self.assertEqual(result, ["ssh b.example"])
        self.assertIn("ssh b.example", self.window.last_toast)

    def test_copy_with_a_deleted_jump_host_reports_it(self):
        self.wallet.save_host(Host(name="b", host="b.example", id="id-b", jump_id="gone"))
        self.window.reload()
        self.select("b")

        self.run_action("copy-command")

        self.assertIn("už neexistuje", self.window.last_toast)

    def test_duplicate_selects_the_copy_below_the_original(self):
        self.vault.passwords["id-a"] = "pw"
        self.select("a")

        self.run_action("duplicate-host")

        self.assertEqual(self.names(), ["a", "a (kopie)", "b", "c"])
        self.assertEqual(self.selected(), "a (kopie)")
        self.assertIsInstance(self.window.get_visible_dialog(), HostDialog)

    def test_delete_asks_first(self):
        self.select("b")

        self.run_action("delete-host")

        self.assertIsInstance(self.window.get_visible_dialog(), Adw.AlertDialog)
        self.assertEqual(self.names(), ["a", "b", "c"])

    def test_move_down_and_up_keep_the_selection(self):
        self.select("a")

        self.run_action("move-down")
        self.assertEqual(self.names(), ["b", "a", "c"])
        self.assertEqual(self.selected(), "a")

        self.run_action("move-up")
        self.assertEqual(self.names(), ["a", "b", "c"])
        self.assertEqual([h.name for h in self.wallet.hosts], ["a", "b", "c"])

    def test_move_past_the_end_does_nothing(self):
        self.select("c")

        self.run_action("move-down")

        self.assertEqual(self.names(), ["a", "b", "c"])

    def test_move_while_searching_jumps_over_hidden_hosts(self):
        self.wallet.save_host(Host(name="a", host="a.example", id="id-a", note="web"))
        self.wallet.save_host(Host(name="c", host="c.example", id="id-c", note="web"))
        self.window.reload()
        self.window.search_entry.set_text("web")
        self.select("a")

        self.run_action("move-down")

        self.assertEqual([h.name for h in self.wallet.hosts], ["b", "c", "a"])
        self.assertEqual(self.names(), ["c", "a"])

    def test_dropping_a_row_on_another_moves_it_there(self):
        [row_a] = [r for r in self.window._rows if r.host.name == "a"]
        [drop] = [c for c in row_a.observe_controllers() if isinstance(c, Gtk.DropTarget)]

        drop.emit("drop", "id-c", 0.0, 0.0)

        self.assertEqual(self.names(), ["c", "a", "b"])


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class HostDialogTest(unittest.TestCase):
    def setUp(self):
        self.saved = []
        # Dialogs must be presented to close; an unmapped parent keeps them off screen.
        self.parent = Adw.ApplicationWindow()

    def make_dialog(self, host, has_password, jump_candidates=()):
        from ssh_wallet.ui.host_dialog import HostDialog

        dialog = HostDialog(host, has_password=has_password, on_save=self.on_save,
                            jump_candidates=list(jump_candidates))
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


    candidates = [Host(name="bastion", host="b", id="id-b"), Host(name="gw", host="g", id="id-g")]

    def test_jump_server_choice_is_saved(self):
        dialog = self.make_dialog(Host(name="pks2", host="h", id="id-t"), False, self.candidates)
        self.assertEqual(dialog.jump_row.get_selected(), 0)  # "Žádný"

        dialog.jump_row.set_selected(2)
        dialog.save_button.emit("clicked")

        self.assertEqual(self.saved[0][0].jump_id, "id-g")

    def test_existing_jump_is_preselected_and_kept(self):
        dialog = self.make_dialog(Host(name="pks2", host="h", id="id-t", jump_id="id-b"), False,
                                  self.candidates)

        self.assertEqual(dialog.jump_row.get_selected(), 1)
        dialog.save_button.emit("clicked")
        self.assertEqual(self.saved[0][0].jump_id, "id-b")

    def test_added_forward_is_saved(self):
        dialog = self.make_dialog(Host(name="pks2", host="h", id="id-t"), False)

        dialog.add_forward_button.emit("clicked")
        [row] = dialog.forward_rows
        row.kind_dropdown.set_selected(1)  # R
        row.port_entry.set_text("8080")
        row.dest_entry.set_text("fe80::1")
        row.dest_port_entry.set_text("80")
        dialog.save_button.emit("clicked")

        self.assertEqual(self.saved[0][0].forwards, [Forward("R", 8080, "fe80::1", 80)])

    def test_new_forward_row_defaults_to_local_localhost(self):
        dialog = self.make_dialog(Host(name="pks2", host="h", id="id-t"), False)

        dialog.add_forward_button.emit("clicked")
        [row] = dialog.forward_rows
        row.port_entry.set_text("5901")
        row.dest_port_entry.set_text("5901")
        dialog.save_button.emit("clicked")

        self.assertEqual(self.saved[0][0].forwards, [Forward("L", 5901, "localhost", 5901)])

    def test_existing_forwards_are_shown_and_can_be_removed(self):
        host = Host(name="pks2", host="h", id="id-t",
                    forwards=[Forward("L", 5901, "localhost", 5901), Forward("R", 8080, "x", 80)])
        dialog = self.make_dialog(host, False)

        self.assertEqual(len(dialog.forward_rows), 2)
        dialog.forward_rows[0].remove_button.emit("clicked")
        dialog.save_button.emit("clicked")

        self.assertEqual(self.saved[0][0].forwards, [Forward("R", 8080, "x", 80)])

    def test_invalid_forward_blocks_saving(self):
        dialog = self.make_dialog(Host(name="pks2", host="h", id="id-t"), False)

        dialog.add_forward_button.emit("clicked")
        dialog.forward_rows[0].port_entry.set_text("abc")

        self.assertFalse(dialog.save_button.get_sensitive())



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

        self.edited, self.connected, self.tunnel_toggles = [], [], []
        return HostRow(host, has_password, on_edit=self.edited.append, on_connect=self.connected.append,
                       on_tunnel=lambda h, on: self.tunnel_toggles.append((h.name, on)))

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


    def test_jump_badge(self):
        row = self.make_row(Host(name="n", host="h", jump_id="id-j"))

        self.assertEqual(self.badges(row), ["Jump"])

    def test_forwards_are_listed_under_the_address(self):
        row = self.make_row(Host(name="n", host="h", user="u", forwards=[
            Forward("L", 5901, "localhost", 5901), Forward("R", 8080, "fe80::1", 80)]))

        self.assertEqual(row.get_subtitle(), "u@h:22\nL 5901 → localhost:5901\nR 8080 → [fe80::1]:80")

    def test_long_address_does_not_wrap_onto_more_lines(self):
        short = self.make_row(Host(name="n", host="10.0.0.6", user="student"))
        long = self.make_row(Host(name="n", host="2001:718:1001:2cf:20c:29ff:fe23:e429", user="student"))

        height = lambda row: row.measure(Gtk.Orientation.VERTICAL, 420)[1]  # natural height
        self.assertEqual(height(long), height(short))

    def test_full_address_is_in_the_tooltip(self):
        row = self.make_row(Host(name="n", host="2001:db8::1", user="student", note="VNC lab"))

        self.assertEqual(row.get_tooltip_text(), "student@[2001:db8::1]:22\nVNC lab")

    def test_tunnel_switch_only_with_forwards(self):
        plain = self.make_row(Host(name="n", host="h"))
        tunnel = self.make_row(Host(name="t", host="h", forwards=[Forward("L", 1, "x", 1)]))

        self.assertEqual(find_widgets(plain, lambda w: isinstance(w, Gtk.Switch)), [])
        self.assertEqual(len(find_widgets(tunnel, lambda w: isinstance(w, Gtk.Switch))), 1)

    def test_tunnel_switch_reports_toggles(self):
        row = self.make_row(Host(name="t", host="h", forwards=[Forward("L", 1, "x", 1)]))

        row.tunnel_switch.set_active(True)
        row.tunnel_switch.set_active(False)

        self.assertEqual(self.tunnel_toggles, [("t", True), ("t", False)])

    def test_showing_state_does_not_report_a_toggle(self):
        row = self.make_row(Host(name="t", host="h", forwards=[Forward("L", 1, "x", 1)]))

        row.show_tunnel_running(True)

        self.assertTrue(row.tunnel_switch.get_active())
        self.assertEqual(self.tunnel_toggles, [])


@unittest.skipUnless(HAS_DISPLAY, "needs a display")
class TunnelWindowTest(unittest.TestCase):
    def setUp(self):
        from ssh_wallet.tunnel import TunnelManager
        from ssh_wallet.ui.window import MainWindow

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wallet = Wallet(HostStore(Path(tmp.name) / "hosts.json"), FakeVault(), launch=RecordingLaunch())
        self.wallet.load()
        self.host = Host(name="pks2", host="10.0.0.6", id="id-t", forwards=[Forward("L", 5901, "localhost", 5901)])
        self.wallet.save_host(self.host)
        self.fake = FakeSpawner()
        self.window = MainWindow(wallet=self.wallet,
                                 tunnels=TunnelManager(spawn=self.fake.spawn, watch=self.fake.watch))

    def row(self):
        [row] = [r for r in self.window._rows if r.host.id == "id-t"]
        return row

    def test_switch_on_starts_the_tunnel_in_the_background(self):
        self.row().tunnel_switch.set_active(True)

        [(argv, *_)] = self.fake.spawned
        self.assertEqual(argv[0], "ssh")
        self.assertIn("5901:localhost:5901", argv)
        self.assertTrue(self.window.tunnels.is_running("id-t"))

    def test_switch_off_stops_it(self):
        self.row().tunnel_switch.set_active(True)
        process = self.fake.spawned[0][3]

        self.row().tunnel_switch.set_active(False)
        self.fake.exit(process)

        self.assertTrue(process.terminated)
        self.assertFalse(self.window.tunnels.is_running("id-t"))
        self.assertFalse(self.row().tunnel_switch.get_active())

    def test_tunnel_that_fails_turns_the_switch_back_off(self):
        self.row().tunnel_switch.set_active(True)

        self.fake.exit(self.fake.spawned[0][3], b"Host key verification failed.\n")

        self.assertFalse(self.row().tunnel_switch.get_active())
        self.assertIn("Host key verification failed.", self.window.last_toast)

    def test_running_tunnel_survives_a_reload(self):
        self.row().tunnel_switch.set_active(True)

        self.window.reload()

        self.assertTrue(self.row().tunnel_switch.get_active())
        self.assertEqual(len(self.fake.spawned), 1)

    def test_missing_jump_host_is_reported_and_switch_stays_off(self):
        broken = Host(name="pks2", host="10.0.0.6", id="id-t", jump_id="gone",
                      forwards=[Forward("L", 5901, "localhost", 5901)])
        self.wallet.save_host(broken)
        self.window.reload()

        self.row().tunnel_switch.set_active(True)

        self.assertEqual(self.fake.spawned, [])
        self.assertFalse(self.row().tunnel_switch.get_active())
        self.assertIn("už neexistuje", self.window.last_toast)


if __name__ == "__main__":
    unittest.main()
