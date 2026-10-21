"""Application entry point."""

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from ssh_wallet.tunnel import TunnelManager  # noqa: E402
from ssh_wallet.ui.style import apply_style  # noqa: E402
from ssh_wallet.ui.window import MainWindow  # noqa: E402

APP_ID = "io.github.krupis294.SshWallet"


class SshWalletApp(Adw.Application):
    def __init__(self, wallet_factory):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._wallet_factory = wallet_factory
        # Tunnels live as long as the app; kitty sessions are independent of it.
        self.tunnels = TunnelManager()

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("win.new-host", ["<Control>n"])
        self.set_accels_for_action("win.edit-host", ["<Control>e"])
        self.set_accels_for_action("win.focus-search", ["<Control>f"])
        self.set_accels_for_action("win.duplicate-host", ["<Control>d"])
        self.set_accels_for_action("win.copy-command", ["<Control><Shift>c"])
        self.set_accels_for_action("win.move-up", ["<Alt>Up"])
        self.set_accels_for_action("win.move-down", ["<Alt>Down"])

    def do_startup(self):
        Adw.Application.do_startup(self)
        apply_style()

    def do_shutdown(self):
        self.tunnels.stop_all()
        Adw.Application.do_shutdown(self)

    def do_activate(self):
        window = self.props.active_window
        if window is None:
            wallet = self._wallet_factory()
            backup = wallet.load()
            window = MainWindow(wallet=wallet, tunnels=self.tunnels, application=self)
            if backup:
                window.toast(f"Soubor s hosty byl nečitelný, přesunut do {backup}.", timeout=0)
        window.present()


def main() -> int:
    from ssh_wallet.store import HostStore, default_path
    from ssh_wallet.vault import SecretVault
    from ssh_wallet.wallet import Wallet

    app = SshWalletApp(lambda: Wallet(HostStore(default_path()), SecretVault()))
    return app.run(sys.argv)
