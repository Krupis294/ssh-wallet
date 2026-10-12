"""Host passwords in the Secret Service keyring (gnome-keyring), keyed by host id."""

import gi

gi.require_version("Secret", "1")
from gi.repository import GLib, Secret  # noqa: E402

SCHEMA_NAME = "io.github.krupis294.SshWallet"


class VaultError(Exception):
    pass


class SecretVault:
    def __init__(self, schema_name: str = SCHEMA_NAME):
        self._schema = Secret.Schema.new(
            schema_name,
            Secret.SchemaFlags.NONE,
            {"entry-id": Secret.SchemaAttributeType.STRING},
        )

    def get(self, entry_id: str) -> str | None:
        try:
            return Secret.password_lookup_sync(self._schema, _attrs(entry_id), None)
        except GLib.Error as e:
            raise VaultError(e.message) from e

    def has(self, entry_id: str) -> bool:
        return self.get(entry_id) is not None

    def set(self, entry_id: str, password: str, label: str) -> None:
        try:
            Secret.password_store_sync(
                self._schema, _attrs(entry_id), Secret.COLLECTION_DEFAULT, label, password, None
            )
        except GLib.Error as e:
            raise VaultError(e.message) from e

    def delete(self, entry_id: str) -> None:
        try:
            Secret.password_clear_sync(self._schema, _attrs(entry_id), None)
        except GLib.Error as e:
            raise VaultError(e.message) from e


def _attrs(entry_id: str) -> dict[str, str]:
    return {"entry-id": entry_id}
