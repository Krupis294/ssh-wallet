"""Main window: searchable host list."""

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from ssh_wallet.launcher import LaunchError  # noqa: E402
from ssh_wallet.model import Host  # noqa: E402
from ssh_wallet.tunnel import TunnelManager  # noqa: E402
from ssh_wallet.ui.host_dialog import HostDialog  # noqa: E402
from ssh_wallet.wallet import Wallet, WalletError  # noqa: E402


class HostRow(Adw.ActionRow):
    def __init__(self, host: Host, has_password: bool, on_edit, on_connect,
                 on_tunnel=None, tunnel_running: bool = False):
        subtitle = "\n".join([host.subtitle(), *(f.describe() for f in host.forwards)])
        super().__init__(title=host.name, subtitle=subtitle, use_markup=False, activatable=True)
        self.host = host
        # Long addresses (IPv6) are shortened in the middle instead of wrapping
        # mid-address; the full one is in the tooltip.
        for label in _labels(self, "subtitle"):
            label.set_wrap(False)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.set_tooltip_text("\n".join(filter(None, [host.subtitle(), host.note])))
        if has_password:
            self.add_suffix(_badge("Heslo", "Heslo uloženo v keyringu"))
        if host.key_path:
            self.add_suffix(_badge("Klíč", f"Klíč {host.key_path}"))
        if host.jump_id:
            self.add_suffix(_badge("Jump", "Připojuje se přes jump server"))

        self.tunnel_switch = None
        if host.forwards:
            self.tunnel_switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=tunnel_running,
                                            tooltip_text="Přesměrování portů na pozadí, bez terminálu")
            self._tunnel_handler = self.tunnel_switch.connect(
                "notify::active", lambda switch, _: on_tunnel(host, switch.get_active()))
            tunnel = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
            tunnel.append(Gtk.Label(label="Tunel", css_classes=["tunnel-label"]))
            tunnel.append(self.tunnel_switch)
            self.add_suffix(tunnel)

        edit = Gtk.Button(label="Upravit", valign=Gtk.Align.CENTER, tooltip_text="Ctrl+E",
                          css_classes=["flat", "row-action"])
        edit.connect("clicked", lambda *_: on_edit(host))
        connect = Gtk.Button(label="Připojit", valign=Gtk.Align.CENTER, tooltip_text="Enter",
                             css_classes=["flat", "row-action", "connect"])
        connect.connect("clicked", lambda *_: on_connect(host))
        self.add_suffix(edit)
        self.add_suffix(connect)

    def show_tunnel_running(self, running: bool) -> None:
        """Reflect the tunnel's state without reporting it as a user toggle."""
        if self.tunnel_switch is None:
            return
        with self.tunnel_switch.handler_block(self._tunnel_handler):
            self.tunnel_switch.set_active(running)


def _labels(widget: Gtk.Widget, css_class: str) -> list[Gtk.Label]:
    found = [widget] if isinstance(widget, Gtk.Label) and widget.has_css_class(css_class) else []
    child = widget.get_first_child()
    while child is not None:
        found += _labels(child, css_class)
        child = child.get_next_sibling()
    return found


def _badge(text: str, tooltip: str) -> Gtk.Label:
    return Gtk.Label(label=text, valign=Gtk.Align.CENTER, tooltip_text=tooltip,
                     css_classes=["badge"])


# Right-click menu of a host row: (label, window action) per section.
MENU_SECTIONS = [
    [("Připojit", "connect-host"), ("Kopírovat ssh příkaz", "copy-command")],
    [("Upravit", "edit-host"), ("Duplikovat", "duplicate-host")],
    [("Smazat", "delete-host")],
]


def host_menu() -> Gio.Menu:
    """The row menu. Its actions act on the selected row, so opening it selects the row.

    The keyboard shortcuts stay out of it: an empty ``accel`` hides them, and
    "Kopírovat ssh příkaz" would otherwise run into its "Shift+Ctrl+C".
    """
    menu = Gio.Menu()
    for items in MENU_SECTIONS:
        section = Gio.Menu()
        for label, action in items:
            item = Gio.MenuItem.new(label, f"win.{action}")
            item.set_attribute_value("accel", GLib.Variant("s", ""))
            section.append_item(item)
        menu.append_section(None, section)
    return menu


def _hints() -> Gtk.Box:
    """Bottom status line with the main keyboard shortcuts."""
    box = Gtk.Box(spacing=20, css_classes=["hints"])
    for key, action in [("Enter", "Připojit"), ("Ctrl+N", "Nový"), ("Ctrl+E", "Upravit"),
                        ("Alt+↑↓", "Přesunout"), ("Esc", "Vymazat hledání")]:
        pair = Gtk.Box(spacing=6)
        pair.append(Gtk.Label(label=key, css_classes=["key"]))
        pair.append(Gtk.Label(label=action))
        box.append(pair)
    return box


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, wallet: Wallet, tunnels: TunnelManager | None = None, **kwargs):
        super().__init__(title="SSH Wallet", default_width=820, default_height=700, **kwargs)
        self.wallet = wallet
        self.tunnels = tunnels or TunnelManager()
        self.last_toast: str | None = None
        self._rows: list[HostRow] = []
        # Where the pointer grabbed the dragged row, so the drag icon stays under it.
        self._drag_hotspot = (0, 0)

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
        # The search glyph is replaced by the ">" prompt. Hiding it here rather than
        # shrinking it to 0px in CSS, which makes GTK log icon-size criticals.
        self.search_entry.get_first_child().set_visible(False)
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
        right_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right_click.connect("pressed", self._on_right_click)
        self.listbox.add_controller(right_click)

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
        self._add_action("focus-search", self.search_entry.grab_focus)
        self._add_action("connect-host", lambda: self._with_selected(self._connect))
        self._add_action("copy-command", lambda: self._with_selected(self._copy_command))
        self._add_action("edit-host", lambda: self._with_selected(self.open_host_dialog))
        self._add_action("duplicate-host", lambda: self._with_selected(self._duplicate))
        self._add_action("delete-host", lambda: self._with_selected(self.confirm_delete))
        self._add_action("move-up", lambda: self._move_selected(-1))
        self._add_action("move-down", lambda: self._move_selected(1))

        self.reload()

    # -- public API -------------------------------------------------------

    def reload(self, select_id: str | None = None) -> None:
        selected = self._selected_row()
        select_id = select_id or (selected.host.id if selected else None)
        for row in self._rows:
            self.listbox.remove(row)
        self._rows = [
            HostRow(h, self.wallet.has_password(h.id), self.open_host_dialog, self._connect,
                    on_tunnel=self._toggle_tunnel, tunnel_running=self.tunnels.is_running(h.id))
            for h in self.wallet.hosts
        ]
        for row in self._rows:
            self._add_drag_and_drop(row)
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
        self.last_toast = message
        self.toast_overlay.add_toast(Adw.Toast(title=GLib.markup_escape_text(message),
                                               timeout=timeout))

    def open_host_dialog(self, host: Host | None) -> None:
        has_password = bool(host) and self.wallet.has_password(host.id)
        dialog = HostDialog(host, has_password, on_save=self._save, on_delete=self.confirm_delete,
                            jump_candidates=self.wallet.jump_candidates(host.id if host else None))
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

    def _on_list_key(self, _controller, keyval, _keycode, state) -> bool:
        row = self._selected_row()
        if row is None:
            return False
        if keyval == Gdk.KEY_Delete:
            self.confirm_delete(row.host)
            return True
        if keyval == Gdk.KEY_Menu or (keyval == Gdk.KEY_F10 and state & Gdk.ModifierType.SHIFT_MASK):
            ok, bounds = row.compute_bounds(self.listbox)
            if ok:
                self._open_menu(row, bounds.get_x() + 24, bounds.get_y() + bounds.get_height())
            return True
        return False

    def _on_right_click(self, gesture, _n_press, x, y) -> None:
        if row := self.listbox.get_row_at_y(int(y)):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self._open_menu(row, x, y)

    def _open_menu(self, row: HostRow, x: float, y: float) -> None:
        self.listbox.select_row(row)
        menu = Gtk.PopoverMenu(menu_model=host_menu(), has_arrow=False, halign=Gtk.Align.START,
                               css_classes=["host-menu"])
        menu.set_parent(self.listbox)
        # PyGObject ignores constructor arguments of boxed types, so the fields are set one by one.
        pointer = Gdk.Rectangle()
        pointer.x, pointer.y, pointer.width, pointer.height = int(x), int(y), 1, 1
        menu.set_pointing_to(pointer)
        # Unparent only after the chosen item's action has run; it is looked up through the parent.
        menu.connect("closed", lambda m: GLib.idle_add(m.unparent))

        # The section separators show up only in an idle callback after the menu is built.
        # Popping up right away sizes the popover without them and scrolls the last item off.
        def popup():
            if menu.get_parent() is not None:
                menu.popup()

        GLib.idle_add(popup)

    def _with_selected(self, callback) -> None:
        # The window shortcuts stay active under an open dialog; leave the list alone then.
        if self.get_visible_dialog() is None and (row := self._selected_row()):
            callback(row.host)

    def _add_drag_and_drop(self, row: HostRow) -> None:
        """Dragging a row onto another puts its host in that row's place."""
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", self._on_drag_prepare, row)
        drag.connect("drag-begin", self._on_drag_begin, row)
        row.add_controller(drag)
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect("drop", lambda _target, host_id, _x, _y: self._move(host_id, row.host.id) or True)
        row.add_controller(drop)

    def _on_drag_prepare(self, _source, x, y, row: HostRow) -> Gdk.ContentProvider:
        self._drag_hotspot = (int(x), int(y))
        return Gdk.ContentProvider.new_for_value(row.host.id)

    def _on_drag_begin(self, source, _drag, row: HostRow) -> None:
        source.set_icon(Gtk.WidgetPaintable.new(row), *self._drag_hotspot)

    def _move_selected(self, step: int) -> None:
        """Swap the selected host with its visible neighbour; hidden hosts are skipped."""
        row, rows = self._selected_row(), self._visible_rows()
        if self.get_visible_dialog() is not None or row not in rows:
            return
        index = rows.index(row) + step
        if 0 <= index < len(rows):
            self._move(row.host.id, rows[index].host.id)

    def _move(self, host_id: str, target_id: str) -> None:
        had_focus = self.listbox.get_focus_child() is not None
        try:
            self.wallet.move_host(host_id, target_id)
        except WalletError as e:
            self.toast(str(e), timeout=6)
            return
        self.reload(select_id=host_id)
        if had_focus and (row := self._selected_row()):
            row.grab_focus()

    def _copy_command(self, host: Host) -> None:
        try:
            command = self.wallet.ssh_command(host)
        except LaunchError as e:
            self.toast(str(e), timeout=6)
            return
        self.get_clipboard().set(command)
        self.toast(f"Zkopírováno: {command}")

    def _duplicate(self, host: Host) -> None:
        try:
            copy = self.wallet.duplicate_host(host.id)
        except WalletError as e:
            self.toast(str(e), timeout=6)
            return
        self.reload(select_id=copy.id)
        self.open_host_dialog(copy)

    def _toggle_tunnel(self, host: Host, on: bool) -> None:
        if not on:
            self.tunnels.stop(host.id)
            return
        try:
            command = self.wallet.tunnel_command(host)
            self.tunnels.start(host.id, host.name, command, on_exit=self._tunnel_exited)
        except LaunchError as e:
            self._show_tunnel(host.id, False)
            self.toast(str(e), timeout=8)
        except OSError as e:
            self._show_tunnel(host.id, False)
            self.toast(f"Tunel nejde spustit: {e.strerror or e}", timeout=8)

    def _tunnel_exited(self, host_id: str, error: str | None) -> None:
        self._show_tunnel(host_id, False)
        if error:
            self.toast(error, timeout=10)

    def _show_tunnel(self, host_id: str, running: bool) -> None:
        for row in self._rows:
            if row.host.id == host_id:
                row.show_tunnel_running(running)

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
        self.tunnels.stop(host.id)
        try:
            self.wallet.delete_host(host.id)
        except WalletError as e:
            self.reload()
            self.toast(str(e), timeout=6)
            return
        self.reload()
        self.toast(f"{host.name} smazán.")
