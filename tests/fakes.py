"""Test doubles for the keyring and the terminal."""

from ssh_wallet.vault import VaultError


class FakeVault:
    """In-memory stand-in for SecretVault. With ``fail=True`` every call raises VaultError."""

    def __init__(self, passwords: dict[str, str] | None = None, fail: bool = False):
        self.passwords = dict(passwords or {})
        self.labels: dict[str, str] = {}
        self.fail = fail

    def _check(self):
        if self.fail:
            raise VaultError("keyring is locked")

    def get(self, entry_id):
        self._check()
        return self.passwords.get(entry_id)

    def has(self, entry_id):
        return self.get(entry_id) is not None

    def set(self, entry_id, password, label):
        self._check()
        self.passwords[entry_id] = password
        self.labels[entry_id] = label

    def delete(self, entry_id):
        self._check()
        self.passwords.pop(entry_id, None)


class FakeTerminal:
    """Answers prompts from a script and records what was asked."""

    def __init__(self, *answers: str | None):
        self.answers = list(answers)
        self.asked: list[tuple[str, bool]] = []
        self.notices: list[str] = []

    def notice(self, text):
        self.notices.append(text)

    def ask(self, prompt, echo):
        self.asked.append((prompt, echo))
        return self.answers.pop(0)
