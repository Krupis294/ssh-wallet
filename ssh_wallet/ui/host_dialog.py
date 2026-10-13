"""Form for adding and editing a host."""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ssh_wallet.model import DEFAULT_PORT, FORWARD_KINDS, Forward, Host  # noqa: E402

NO_KEY_SUBTITLE = "Výchozí klíče ssh a ~/.ssh/config"
NO_JUMP = "Žádný"


def _port(text: str) -> int:
    """Port typed into an entry; 0 (rejected by validation) when it is not a number."""
    try:
        return int(text.strip())
    except ValueError:
        return 0


class ForwardRow(Adw.PreferencesRow):
    """One port forward: type, port, destination host and port."""

    def __init__(self, forward: Forward | None, on_change, on_remove):
        super().__init__(activatable=False, css_classes=["forward-row"])
        self.kind_dropdown = Gtk.DropDown.new_from_strings(list(FORWARD_KINDS))
        self.kind_dropdown.set_valign(Gtk.Align.CENTER)
        self.kind_dropdown.set_tooltip_text(
            "L: port u tebe vede na cíl za serverem. R: port na serveru vede na cíl u tebe.")
        self.port_entry = _port_entry("Port, který se otevře")
        self.dest_entry = Gtk.Entry(hexpand=True, placeholder_text="Cílový host",
                                    valign=Gtk.Align.CENTER, text="localhost")
        self.dest_port_entry = _port_entry("Cílový port")
        self.remove_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                        tooltip_text="Odebrat přesměrování", css_classes=["flat"])

        box = Gtk.Box(spacing=8)
        for widget in (self.kind_dropdown, self.port_entry, Gtk.Label(label="→", css_classes=["dim-label"]),
                       self.dest_entry, Gtk.Label(label=":", css_classes=["dim-label"]),
                       self.dest_port_entry, self.remove_button):
            box.append(widget)
        self.set_child(box)

        if forward:
            self.kind_dropdown.set_selected(FORWARD_KINDS.index(forward.kind))
            self.port_entry.set_text(str(forward.port))
            self.dest_entry.set_text(forward.dest_host)
            self.dest_port_entry.set_text(str(forward.dest_port))

        self.kind_dropdown.connect("notify::selected", lambda *_: on_change())
        for entry in (self.port_entry, self.dest_entry, self.dest_port_entry):
            entry.connect("changed", lambda *_: on_change())
        self.remove_button.connect("clicked", lambda *_: on_remove(self))

    def forward(self) -> Forward:
        return Forward(kind=FORWARD_KINDS[self.kind_dropdown.get_selected()],
                       port=_port(self.port_entry.get_text()),
                       dest_host=self.dest_entry.get_text(),
                       dest_port=_port(self.dest_port_entry.get_text()))


def _port_entry(placeholder: str) -> Gtk.Entry:
    return Gtk.Entry(width_chars=5, max_width_chars=5, placeholder_text="port", tooltip_text=placeholder,
                     input_purpose=Gtk.InputPurpose.DIGITS, valign=Gtk.Align.CENTER)


class HostDialog(Adw.Dialog):
    """``on_save(host, password, remove_password)`` returns an error message or None.

    ``password`` is None when the field was left empty (keep the stored one).
    """

    def __init__(self, host: Host | None, has_password: bool, on_save, on_delete=None,
                 jump_candidates: list[Host] = ()):
        super().__init__(title="Upravit host" if host else "Nový host", content_width=600)
        self._original = host
        self._on_save = on_save
        self._key_path = host.key_path if host else ""
        self._jump_candidates = list(jump_candidates)
        self.forward_rows: list[ForwardRow] = []

        cancel = Gtk.Button(label="Zrušit")
        cancel.connect("clicked", lambda *_: self.close())
        self.save_button = Gtk.Button(label="Uložit", css_classes=["suggested-action"])
        self.save_button.connect("clicked", self._save)
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.save_button)

        self.name_row = Adw.EntryRow(title="Název")
        self.host_row = Adw.EntryRow(title="Host (IP adresa nebo jméno)")
        self.port_row = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.port_row.set_title("Port")
        self.port_row.set_value(DEFAULT_PORT)
        self.user_row = Adw.EntryRow(title="Username")
        self.password_row = Adw.PasswordEntryRow(
            title="Nové heslo (prázdné = ponechat uložené)" if has_password else "Heslo (nepovinné)"
        )
        self.remove_password_row = Adw.SwitchRow(title="Odebrat uložené heslo", visible=has_password)
        self.remove_password_row.connect(
            "notify::active",
            lambda row, _: self.password_row.set_sensitive(not row.get_active()),
        )
        self.key_row = self._build_key_row()
        self.jump_row = Adw.ComboRow(
            title="Jump server", subtitle="Připojení přes jiný uložený host",
            model=Gtk.StringList.new([NO_JUMP, *(h.name for h in self._jump_candidates)]),
        )

        group = Adw.PreferencesGroup()
        for row in (self.name_row, self.host_row, self.port_row, self.user_row,
                    self.password_row, self.remove_password_row, self.key_row, self.jump_row):
            group.add(row)

        self.add_forward_button = Gtk.Button(label="+ Přidat", valign=Gtk.Align.CENTER,
                                             css_classes=["flat"])
        self.add_forward_button.connect("clicked", lambda *_: self._add_forward(None))
        self.forwards_group = Adw.PreferencesGroup(
            title="Přesměrování portů",
            description="Tunel se zapíná přepínačem v seznamu hostů a běží na pozadí bez terminálu.",
            header_suffix=self.add_forward_button,
        )

        self.note_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8,
                                      bottom_margin=8, left_margin=8, right_margin=8)
        note_scroll = Gtk.ScrolledWindow(child=self.note_view, min_content_height=80,
                                         hscrollbar_policy=Gtk.PolicyType.NEVER)
        note_group = Adw.PreferencesGroup(title="Poznámka")
        note_group.add(Gtk.Frame(child=note_scroll, css_classes=["note-frame"]))

        page = Adw.PreferencesPage()
        page.add(group)
        page.add(self.forwards_group)
        page.add(note_group)
        if host and on_delete:
            delete = Gtk.Button(label="Smazat položku", halign=Gtk.Align.CENTER,
                                css_classes=["destructive-action"])
            delete.connect("clicked", lambda *_: (self.close(), on_delete(host)))
            delete_group = Adw.PreferencesGroup()
            delete_group.add(delete)
            page.add(delete_group)

        self.toast_overlay = Adw.ToastOverlay(child=page)
        toolbar = Adw.ToolbarView(content=self.toast_overlay)
        toolbar.add_top_bar(header)
        self.set_child(toolbar)

        if host:
            self.name_row.set_text(host.name)
            self.host_row.set_text(host.host)
            self.port_row.set_value(host.port)
            self.user_row.set_text(host.user)
            self.note_view.get_buffer().set_text(host.note)
            ids = [h.id for h in self._jump_candidates]
            if host.jump_id in ids:
                self.jump_row.set_selected(ids.index(host.jump_id) + 1)
            for forward in host.forwards:
                self._add_forward(forward)
        self._show_key_path()

        for row in (self.name_row, self.host_row, self.user_row):
            row.connect("changed", lambda *_: self._validate())
            row.connect("entry-activated", self._save)
        self.port_row.connect("notify::value", lambda *_: self._validate())
        self.jump_row.connect("notify::selected", lambda *_: self._validate())
        self.password_row.connect("entry-activated", self._save)
        self._validate()
        self.set_focus(self.name_row)

    def _add_forward(self, forward: Forward | None) -> None:
        row = ForwardRow(forward, on_change=self._validate, on_remove=self._remove_forward)
        self.forward_rows.append(row)
        self.forwards_group.add(row)
        self._validate()

    def _remove_forward(self, row: ForwardRow) -> None:
        self.forward_rows.remove(row)
        self.forwards_group.remove(row)
        self._validate()

    def _build_key_row(self) -> Adw.ActionRow:
        row = Adw.ActionRow(title="SSH klíč")
        choose = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER,
                            tooltip_text="Vybrat soubor s klíčem", css_classes=["flat"])
        choose.connect("clicked", self._choose_key)
        self._clear_key_button = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER,
                                            tooltip_text="Nepoužívat konkrétní klíč",
                                            css_classes=["flat"])
        self._clear_key_button.connect("clicked", lambda *_: self._set_key_path(""))
        row.add_suffix(choose)
        row.add_suffix(self._clear_key_button)
        return row

    def _show_key_path(self) -> None:
        self.key_row.set_subtitle(GLib.markup_escape_text(self._key_path) or NO_KEY_SUBTITLE)
        self._clear_key_button.set_visible(bool(self._key_path))

    def _set_key_path(self, path: str) -> None:
        self._key_path = path
        self._show_key_path()

    def _choose_key(self, *_):
        dialog = Gtk.FileDialog(title="Vyber soubor se SSH klíčem")
        ssh_dir = Path.home() / ".ssh"
        if ssh_dir.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(ssh_dir)))
        root = self.get_root()
        dialog.open(root if isinstance(root, Gtk.Window) else None, None, self._on_key_chosen)

    def _on_key_chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return  # cancelled
        path = file.get_path()
        home = str(Path.home())
        if path.startswith(home + "/"):
            path = "~" + path[len(home):]
        self._set_key_path(path)

    def _build_host(self) -> Host:
        buffer = self.note_view.get_buffer()
        fields = dict(
            name=self.name_row.get_text(),
            host=self.host_row.get_text(),
            port=int(self.port_row.get_value()),
            user=self.user_row.get_text(),
            key_path=self._key_path,
            note=buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip(),
            jump_id=self._selected_jump_id(),
            forwards=[row.forward() for row in self.forward_rows],
        )
        if self._original:
            fields["id"] = self._original.id
        return Host(**fields)

    def _selected_jump_id(self) -> str:
        index = self.jump_row.get_selected()
        return self._jump_candidates[index - 1].id if 0 < index <= len(self._jump_candidates) else ""

    def _validate(self) -> None:
        errors = self._build_host().errors()
        self.save_button.set_sensitive(not errors)
        self.save_button.set_tooltip_text("\n".join(errors) or None)

    def _save(self, *_):
        if not self.save_button.get_sensitive():
            return
        remove = self.remove_password_row.get_visible() and self.remove_password_row.get_active()
        password = None if remove else (self.password_row.get_text() or None)
        error = self._on_save(self._build_host(), password, remove)
        if error:
            self.toast_overlay.add_toast(Adw.Toast(title=GLib.markup_escape_text(error), timeout=6))
        else:
            self.close()
