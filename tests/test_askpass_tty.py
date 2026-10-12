"""Runs bin/ssh-wallet-askpass under a real pseudo-terminal, the way ssh does."""

import fcntl
import os
import pty
import select
import subprocess
import tempfile
import termios
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ssh-wallet-askpass"


def make_controlling_tty():
    # stdin is the pty slave; adopt it as controlling terminal so /dev/tty works.
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class AskpassOnTerminalTest(unittest.TestCase):
    def setUp(self):
        self.master, slave = pty.openpty()
        self.addCleanup(os.close, self.master)
        env = {k: v for k, v in os.environ.items() if k != "SSH_WALLET_ID"}
        env["XDG_RUNTIME_DIR"] = self.enterContext(tempfile.TemporaryDirectory())
        self.spawn = lambda prompt: subprocess.Popen(
            [str(SCRIPT), prompt], stdin=slave, stderr=slave, stdout=subprocess.PIPE,
            start_new_session=True, preexec_fn=make_controlling_tty, env=env,
        )
        self.addCleanup(os.close, slave)

    def read_until(self, text: str) -> str:
        seen = ""
        while text not in seen:
            ready, _, _ = select.select([self.master], [], [], 5)
            self.assertTrue(ready, f"timed out waiting for {text!r}, got {seen!r}")
            seen += os.read(self.master, 1024).decode()
        return seen

    def test_yes_no_question_is_answered_from_terminal(self):
        proc = self.spawn("Are you sure you want to continue connecting (yes/no/[fingerprint])? ")
        self.read_until("(yes/no/[fingerprint])? ")

        os.write(self.master, b"yes\n")
        out, _ = proc.communicate(timeout=5)

        self.assertEqual(out, b"yes\n")
        self.assertEqual(proc.returncode, 0)

    def test_passphrase_is_read_without_echo(self):
        proc = self.spawn("Enter passphrase for key '/k': ")
        self.read_until("Enter passphrase for key '/k': ")

        os.write(self.master, b"hunter2\n")
        out, _ = proc.communicate(timeout=5)

        self.assertEqual(out, b"hunter2\n")
        echoed = os.read(self.master, 1024).decode() if select.select([self.master], [], [], 0.2)[0] else ""
        self.assertNotIn("hunter2", echoed)

    def test_cancel_with_end_of_input_exits_non_zero(self):
        proc = self.spawn("Are you sure you want to continue connecting (yes/no)? ")
        self.read_until("(yes/no)? ")

        os.write(self.master, b"\x04")  # Ctrl+D
        out, _ = proc.communicate(timeout=5)

        self.assertEqual(out, b"")
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
