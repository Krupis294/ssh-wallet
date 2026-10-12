import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from ssh_wallet.askpass import Action, Markers, decide, process_key, run
from tests.fakes import FakeTerminal, FakeVault

PASSWORD_PROMPT = "kuba@10.0.0.5's password: "
HOSTKEY_PROMPT = (
    "The authenticity of host '10.0.0.5 (10.0.0.5)' can't be established.\n"
    "ED25519 key fingerprint is SHA256:abc.\n"
    "Are you sure you want to continue connecting (yes/no/[fingerprint])? "
)
PASSPHRASE_PROMPT = "Enter passphrase for key '/home/kuba/.ssh/id_ed25519': "


def dead_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


class DecideTest(unittest.TestCase):
    def test_prompts(self):
        cases = [
            (PASSWORD_PROMPT, False, Action.USE_STORED),
            (PASSWORD_PROMPT, True, Action.RETRY),
            ("(kuba@nas) Password: ", False, Action.USE_STORED),
            ("Password for kuba@nas: ", False, Action.USE_STORED),
            (HOSTKEY_PROMPT, False, Action.ASK_VISIBLE),
            (PASSPHRASE_PROMPT, False, Action.ASK_HIDDEN),
            ("(kuba@nas) Verification code: ", False, Action.ASK_HIDDEN),
            ("", False, Action.ASK_HIDDEN),
        ]
        for prompt, used, expected in cases:
            with self.subTest(prompt=prompt, used=used):
                self.assertEqual(decide(prompt, already_used=used), expected)


class MarkersTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "ssh-wallet"
        self.markers = Markers(self.dir)

    def test_mark_is_per_process(self):
        self.markers.mark(os.getpid())

        self.assertTrue(self.markers.used(os.getpid()))
        self.assertFalse(self.markers.used(os.getppid()))

    def test_prune_removes_markers_of_finished_processes(self):
        gone = dead_pid()
        (self.dir).mkdir(parents=True)
        (self.dir / f"askpass-{gone}-123").touch()
        self.markers.mark(os.getpid())

        self.markers.prune()

        self.assertEqual(os.listdir(self.dir), [f"askpass-{process_key(os.getpid())}"])

    def test_marker_of_reused_pid_does_not_count(self):
        self.dir.mkdir(parents=True)
        (self.dir / f"askpass-{os.getpid()}-1").touch()  # same pid, different start time

        self.assertFalse(self.markers.used(os.getpid()))
        self.markers.prune()
        self.assertEqual(os.listdir(self.dir), [])


class ProcessKeyTest(unittest.TestCase):
    def test_live_process_key_combines_pid_and_start_time(self):
        pid, start = process_key(os.getpid()).split("-")

        self.assertEqual(pid, str(os.getpid()))
        self.assertTrue(start.isdigit())

    def test_dead_process_has_no_key(self):
        self.assertIsNone(process_key(dead_pid()))


class RunTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.markers = Markers(Path(tmp.name))
        self.pid = os.getpid()

    def run_prompt(self, prompt, terminal, vault=None, entry_id="id-1"):
        if vault is None:
            vault = FakeVault({"id-1": "s3cret"})
        return run(prompt, entry_id=entry_id, vault=vault, terminal=terminal,
                   markers=self.markers, ssh_pid=self.pid)

    def test_first_password_prompt_answers_with_stored_password(self):
        terminal = FakeTerminal()

        self.assertEqual(self.run_prompt(PASSWORD_PROMPT, terminal), "s3cret")
        self.assertEqual(terminal.asked, [])

    def test_second_password_prompt_asks_user_instead(self):
        self.run_prompt(PASSWORD_PROMPT, FakeTerminal())
        terminal = FakeTerminal("typed")

        self.assertEqual(self.run_prompt(PASSWORD_PROMPT, terminal), "typed")
        self.assertEqual(terminal.asked, [(PASSWORD_PROMPT, False)])
        self.assertEqual(terminal.notices, ["Uložené heslo nebylo přijato, zadej ho ručně."])

    def test_host_key_question_is_asked_visibly(self):
        terminal = FakeTerminal("yes")

        self.assertEqual(self.run_prompt(HOSTKEY_PROMPT, terminal), "yes")
        self.assertEqual(terminal.asked, [(HOSTKEY_PROMPT, True)])

    def test_host_key_question_does_not_use_up_stored_password(self):
        self.run_prompt(HOSTKEY_PROMPT, FakeTerminal("yes"))

        self.assertEqual(self.run_prompt(PASSWORD_PROMPT, FakeTerminal()), "s3cret")

    def test_key_passphrase_is_asked_hidden(self):
        terminal = FakeTerminal("phrase")

        self.assertEqual(self.run_prompt(PASSPHRASE_PROMPT, terminal), "phrase")
        self.assertEqual(terminal.asked, [(PASSPHRASE_PROMPT, False)])

    def test_missing_stored_password_falls_back_to_asking(self):
        terminal = FakeTerminal("typed")

        result = self.run_prompt(PASSWORD_PROMPT, terminal, vault=FakeVault())

        self.assertEqual(result, "typed")
        self.assertEqual(terminal.asked, [(PASSWORD_PROMPT, False)])

    def test_keyring_error_falls_back_to_asking(self):
        terminal = FakeTerminal("typed")

        result = self.run_prompt(PASSWORD_PROMPT, terminal, vault=FakeVault(fail=True))

        self.assertEqual(result, "typed")
        self.assertEqual(terminal.notices, ["Heslo z keyringu nelze načíst: keyring is locked"])

    def test_without_entry_id_asks(self):
        terminal = FakeTerminal("typed")

        self.assertEqual(self.run_prompt(PASSWORD_PROMPT, terminal, entry_id=None), "typed")

    def test_without_vault_asks(self):
        terminal = FakeTerminal("typed")

        result = run(PASSWORD_PROMPT, entry_id="id-1", vault=None, terminal=terminal,
                     markers=self.markers, ssh_pid=self.pid)

        self.assertEqual(result, "typed")

    def test_cancelled_question_returns_none(self):
        self.assertIsNone(self.run_prompt(HOSTKEY_PROMPT, FakeTerminal(None)))


if __name__ == "__main__":
    unittest.main()
