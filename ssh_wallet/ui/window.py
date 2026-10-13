"""Main window: searchable host list."""

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ssh_wallet.launcher import LaunchError  # noqa: E402
from ssh_wallet.model import Host  # noqa: E402
from ssh_wallet.ui.host_dialog import HostDialog  # noqa: E402
from ssh_wallet.wallet import Wallet, WalletError  # noqa: E402


class HostRow(Adw.ActionRow):
    def __init__(self, host: Host, has_password: bool, on_edit, on_connect):
        super().__init__(title=host.name, subtitle=host.subtitle(), use_markup=False,
                         activatable=True)
        self.host = host
        if host.note:
            self.set_tooltip_text(host.note)
        if has_password:
            self.add_suffix(_badge("Heslo", "Heslo uloženo v keyringu"))
        if host.key_path:
            self.add_suffix(_badge("Klíč", f"Klíč {host.key_path}"))
        edit = Gtk.Button(label="Upravit", valign=Gtk.Align.CENTER, tooltip_text="Ctrl+E",
                          css_classes=["flat", "row-action"])
        edit.connect("clicked", lambda *_: on_edit(host))
        connect = Gtk.Button(label="Připojit", valign=Gtk.Align.CENTER, tooltip_text="Enter",
                             css_classes=["flat", "row-action", "connect"])
        connect.connect("clicked", lambda *_: on_connect(host))
        self.add_suffix(edit)
        self.add_suffix(connect)


def _badge(text: str, tooltip: str) -> Gtk.Label:
    return Gtk.Label(label=text, valign=Gtk.Align.CENTER, tooltip_text=tooltip,
                     css_classes=["badge"])


def _hints() -> Gtk.Box:
    """Bottom status line with the main keyboard shortcuts."""
    box = Gtk.Box(spacing=20, css_classes=["hints"])
    for key, action in [("Enter", "Připojit"), ("Ctrl+N", "Nový"), ("Ctrl+E", "Upravit"),
                        ("Esc", "Vymazat hledání")]:
        pair = Gtk.Box(spacing=6)
        pair.append(Gtk.Label(label=key, css_classes=["key"]))
        pair.append(Gtk.Label(label=action))
        box.append(pair)
    return box


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, wallet: Wallet, **kwargs):
        super().__init__(title="SSH Wallet", default_width=720, default_height=700, **kwargs)
        self.wallet = wallet
        self._rows: list[HostRow] = []

        add = Gtk.Button(label="+ Nový", tooltip_text="Ctrl+N", action_name="win.new-host",
                         css_classes=["flat"])
        header = Adw.HeaderBar(title_widget=Gtk.Label(label="SSH Wallet", css_classes=["app-title"]))
        header.pack_end(add)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Hledat", hexpand=True)
        self.search_entry.connect("changed", lambda *_: self._update_view())
        self.search_entry.connect("activate", lambda *_: self.connect_selected())
        self.search_entry.connect("stop-search", lambda entry: entry.set_text(""))
        search_keys = Gtk.EventControllerKey()
        search_keys.connect("key-pressed", self._on_search_key)
        self.search_entry.add_controller(search_keys)
        self.search_entry.set_key_capture_widget(self)
        prompt_bar = Gtk.Box(css_classes=["prompt-bar"])
        prompt_bar.append(Gtk.Label(label=">", css_classes=["prompt"]))
        prompt_bar.append(self.search_entry)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE,
                                   css_classes=["host-list"], valign=Gtk.Align.START)
        self.listbox.set_filter_func(lambda row: row.host.matches(self.search_entry.get_text()))
        self.listbox.connect("row-activated", lambda _, row: self._connect(row.host))
        list_keys = Gtk.EventControllerKey()
        list_keys.connect("key-pressed", self._on_list_key)
        self.listbox.add_controller(list_keys)

        list_page = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                       child=self.listbox)
        empty_page = Adw.StatusPage(
            title="Žádné hosty", description="Ctrl+N přidá první.",
            child=Gtk.Button(label="+ Nový host", action_name="win.new-host",
                             halign=Gtk.Align.CENTER, css_classes=["suggested-action"]),
        )
        no_results_page = Adw.StatusPage(title="Nic nenalezeno",
                                         description="Esc vymaže hledání.")

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(list_page, "list")
        self.stack.add_named(empty_page, "empty")
        self.stack.add_named(no_results_page, "no-results")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(prompt_bar)
        content.append(self.stack)
        self.toast_overlay = Adw.ToastOverlay(child=content)
        toolbar = Adw.ToolbarView(content=self.toast_overlay)
        toolbar.add_top_bar(header)
        toolbar.add_bottom_bar(_hints())
        self.set_content(toolbar)

        self._add_action("new-host", lambda: self.open_host_dialog(None))
        self._add_action("edit-host", self._edit_selected)
        self._add_action("focus-search", self.search_entry.grab_focus)

        self.reload()

    # -- public API -------------------------------------------------------

    def reload(self, select_id: str | None = None) -> None:
        selected = self._selected_row()
        select_id = select_id or (selected.host.id if selected else None)
        for row in self._rows:
            self.listbox.remove(row)
        self._rows = [
            HostRow(h, self.wallet.has_password(h.id), self.open_host_dialog, self._connect)
            for h in self.wallet.hosts
        ]
        for row in self._rows:
            self.listbox.append(row)
        self._update_view(select_id)

    def visible_hosts(self) -> list[Host]:
        return [row.host for row in self._visible_rows()]

    def select_next(self, step: int) -> None:
        """Move the selection by ``step`` rows within the visible (filtered) rows."""
        rows = self._visible_rows()
        if not rows:
            return
        current = self._selected_row()
        index = rows.index(current) + step if current in rows else 0
        row = rows[max(0, min(index, len(rows) - 1))]
        self.listbox.select_row(row)
        if self.listbox.get_focus_child() is not None:
            row.grab_focus()

    def connect_selected(self) -> None:
        row = self._selected_row()
        rows = self._visible_rows()
        if row not in rows:
            row = rows[0] if rows else None
        if row:
            self._connect(row.host)

    def toast(self, message: str, timeout: int = 4) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=GLib.markup_escape_text(message),
                                               timeout=timeout))

    def open_host_dialog(self, host: Host | None) -> None:
        has_password = bool(host) and self.wallet.has_password(host.id)
        dialog = HostDialog(host, has_password, on_save=self._save, on_delete=self.confirm_delete)
        dialog.present(self)

    def confirm_delete(self, host: Host) -> None:
        dialog = Adw.AlertDialog(heading=f"Smazat {host.name}?",
                                 body="Položka i uložené heslo budou odstraněny.")
        dialog.add_response("cancel", "Zrušit")
        dialog.add_response("delete", "Smazat")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _, response: response == "delete" and self._delete(host))
        dialog.present(self)

    # -- internals --------------------------------------------------------

    def _add_action(self, name: str, callback) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda *_: callback())
        self.add_action(action)

    def _visible_rows(self) -> list[HostRow]:
        query = self.search_entry.get_text()
        return [row for row in self._rows if row.host.matches(query)]

    def _selected_row(self) -> HostRow | None:
        return self.listbox.get_selected_row()

    def _update_view(self, select_id: str | None = None) -> None:
        self.listbox.invalidate_filter()
        rows = self._visible_rows()
        if not self._rows:
            self.stack.set_visible_child_name("empty")
        elif not rows:
            self.stack.set_visible_child_name("no-results")
        else:
            self.stack.set_visible_child_name("list")

        wanted = next((r for r in rows if r.host.id == select_id), None)
        if wanted is None and self._selected_row() not in rows:
            wanted = rows[0] if rows else None
        if wanted is not None:
            self.listbox.select_row(wanted)
        elif not rows:
            self.listbox.unselect_all()

    def _on_search_key(self, _controller, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Down:
            self.select_next(1)
            return True
        if keyval == Gdk.KEY_Up:
            self.select_next(-1)
            return True
        return False

    def _on_list_key(self, _controller, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Delete and (row := self._selected_row()):
            self.confirm_delete(row.host)
            return True
        return False

    def _edit_selected(self) -> None:
        if row := self._selected_row():
            self.open_host_dialog(row.host)

    def _connect(self, host: Host) -> None:
        try:
            self.wallet.connect(host)
        except LaunchError as e:
            self.toast(str(e), timeout=6)

    def _save(self, host: Host, password: str | None, remove_password: bool) -> str | None:
        try:
            self.wallet.save_host(host, password, remove_password)
        except WalletError as e:
            return str(e)
        self.reload(select_id=host.id)
        if host.key_path and not Path(os.path.expanduser(host.key_path)).is_file():
            self.toast(f"Upozornění: soubor s klíčem {host.key_path} neexistuje.", timeout=6)
        return None

    def _delete(self, host: Host) -> None:
        try:
            self.wallet.delete_host(host.id)
        except WalletError as e:
            self.reload()
            self.toast(str(e), timeout=6)
            return
        self.reload()
        self.toast(f"{host.name} smazán.")
