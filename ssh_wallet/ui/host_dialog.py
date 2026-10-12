"""Form for adding and editing a host."""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ssh_wallet.model import DEFAULT_PORT, Host  # noqa: E402

NO_KEY_SUBTITLE = "Výchozí klíče ssh a ~/.ssh/config"


class HostDialog(Adw.Dialog):
    """``on_save(host, password, remove_password)`` returns an error message or None.

    ``password`` is None when the field was left empty (keep the stored one).
    """

    def __init__(self, host: Host | None, has_password: bool, on_save, on_delete=None):
        super().__init__(title="Upravit host" if host else "Nový host", content_width=480)
        self._original = host
        self._on_save = on_save
        self._key_path = host.key_path if host else ""

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

        group = Adw.PreferencesGroup()
        for row in (self.name_row, self.host_row, self.port_row, self.user_row,
                    self.password_row, self.remove_password_row, self.key_row):
            group.add(row)

        self.note_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8,
                                      bottom_margin=8, left_margin=8, right_margin=8)
        note_scroll = Gtk.ScrolledWindow(child=self.note_view, min_content_height=80,
                                         hscrollbar_policy=Gtk.PolicyType.NEVER)
        note_group = Adw.PreferencesGroup(title="Poznámka")
        note_group.add(Gtk.Frame(child=note_scroll))

        page = Adw.PreferencesPage()
        page.add(group)
        page.add(note_group)
        if host and on_delete:
            delete = Gtk.Button(label="Smazat položku", halign=Gtk.Align.CENTER,
                                css_classes=["destructive-action", "pill"])
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
        self._show_key_path()

        for row in (self.name_row, self.host_row, self.user_row):
            row.connect("changed", lambda *_: self._validate())
            row.connect("entry-activated", self._save)
        self.port_row.connect("notify::value", lambda *_: self._validate())
        self.password_row.connect("entry-activated", self._save)
        self._validate()
        self.set_focus(self.name_row)

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
        )
        if self._original:
            fields["id"] = self._original.id
        return Host(**fields)

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
