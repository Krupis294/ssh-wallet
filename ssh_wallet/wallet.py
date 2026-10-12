"""Application logic shared by the UI: host list, passwords and connecting."""

from pathlib import Path

from ssh_wallet import launcher
from ssh_wallet.model import Host
from ssh_wallet.store import HostStore
from ssh_wallet.vault import VaultError


class WalletError(Exception):
    pass


class Wallet:
    def __init__(self, store: HostStore, vault, launch=launcher.launch,
                 askpass_path: Path = launcher.ASKPASS_PATH):
        self._store = store
        self._vault = vault
        self._launch = launch
        self._askpass_path = askpass_path
        self._hosts: list[Host] = []

    def load(self) -> Path | None:
        """Load hosts; returns the backup path if the hosts file was unreadable."""
        result = self._store.load()
        self._hosts = result.hosts
        return result.backup_path

    @property
    def hosts(self) -> list[Host]:
        return sorted(self._hosts, key=lambda h: h.name.casefold())

    def has_password(self, host_id: str) -> bool:
        try:
            return self._vault.has(host_id)
        except VaultError:
            return False

    def save_host(self, host: Host, password: str | None = None,
                  remove_password: bool = False) -> None:
        """Add or replace ``host``. ``password=None`` keeps the stored password.

        The keyring is updated first: if that fails, the hosts file is untouched.
        """
        if errors := host.errors():
            raise WalletError(" ".join(errors))
        try:
            if remove_password:
                self._vault.delete(host.id)
            elif password:
                self._vault.set(host.id, password, label=f"SSH Wallet: {host.name}")
        except VaultError as e:
            raise WalletError(f"Heslo nelze uložit do keyringu: {e}") from e

        hosts = [h for h in self._hosts if h.id != host.id] + [host]
        self._write(hosts)

    def delete_host(self, host_id: str) -> None:
        self._write([h for h in self._hosts if h.id != host_id])
        try:
            self._vault.delete(host_id)
        except VaultError as e:
            raise WalletError(f"Položka smazána, ale heslo z keyringu odstranit nešlo: {e}") from e

    def connect(self, host: Host) -> None:
        """Open a kitty window with ssh to ``host``. Raises launcher.LaunchError."""
        command = launcher.build_command(host, self.has_password(host.id), self._askpass_path)
        self._launch(command)

    def _write(self, hosts: list[Host]) -> None:
        try:
            self._store.save(hosts)
        except OSError as e:
            raise WalletError(f"Soubor {self._store.path} nelze uložit: {e.strerror or e}") from e
        self._hosts = hosts
