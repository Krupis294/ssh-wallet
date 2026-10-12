import os
import subprocess
import unittest
from pathlib import Path

from ssh_wallet.launcher import WRAPPER, Command, LaunchError, build_command, launch
from ssh_wallet.model import Host

ASKPASS = Path("/opt/wallet/bin/ssh-wallet-askpass")
KITTY_PREFIX = ["kitty", "--class", "ssh-wallet-session", "-o", "term=xterm-256color"]


def ssh_part(command: Command) -> list[str]:
    """The ssh invocation handed to the wrapper (after `sh -c WRAPPER sh`)."""
    i = command.argv.index("-c")
    return command.argv[i + 3:]


class BuildCommandTest(unittest.TestCase):
    def test_full_command_for_plain_host(self):
        host = Host(name="mikrotik", host="192.168.122.19", user="admin", id="id-1")

        command = build_command(host, has_password=False, askpass_path=ASKPASS)

        self.assertEqual(command.argv, KITTY_PREFIX + [
            "--title=mikrotik",
            "sh", "-c", WRAPPER, "sh",
            "ssh", "-p", "22", "--", "admin@192.168.122.19",
        ])
        self.assertEqual(command.env, {})

    def test_port_and_key(self):
        host = Host(name="nas", host="nas", user="kuba", port=2222, key_path="~/.ssh/nas_key")

        command = build_command(host, has_password=False, askpass_path=ASKPASS)

        self.assertEqual(ssh_part(command), [
            "ssh", "-p", "2222",
            "-i", str(Path.home() / ".ssh/nas_key"), "-o", "IdentitiesOnly=yes",
            "--", "kuba@nas",
        ])

    def test_without_user_destination_is_bare_host(self):
        command = build_command(Host(name="n", host="nas"), has_password=False, askpass_path=ASKPASS)

        self.assertEqual(ssh_part(command)[-2:], ["--", "nas"])

    def test_password_entry_routes_prompts_through_askpass(self):
        host = Host(name="m", host="h", id="id-1")

        command = build_command(host, has_password=True, askpass_path=ASKPASS)

        self.assertEqual(command.env, {
            "SSH_ASKPASS": "/opt/wallet/bin/ssh-wallet-askpass",
            "SSH_ASKPASS_REQUIRE": "force",
            "SSH_WALLET_ID": "id-1",
        })

    def test_shell_metacharacters_stay_single_arguments(self):
        host = Host(name="a'; rm -rf ~ #", host="h;id", user="u$(id)")

        command = build_command(host, has_password=False, askpass_path=ASKPASS)

        self.assertIn("--title=a'; rm -rf ~ #", command.argv)
        self.assertEqual(ssh_part(command)[-1], "u$(id)@h;id")


class WrapperTest(unittest.TestCase):
    def run_wrapper(self, *cmd: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(["sh", "-c", WRAPPER, "sh", *cmd],
                              input=stdin, capture_output=True, text=True, timeout=5)

    def test_ssh_failure_keeps_window_open_until_enter(self):
        result = self.run_wrapper("sh", "-c", "exit 255", stdin="\n")

        self.assertIn("Spojení selhalo", result.stdout)
        self.assertEqual(result.returncode, 255)

    def test_normal_exit_closes_immediately(self):
        result = self.run_wrapper("sh", "-c", "exit 0")

        self.assertEqual(result.stdout, "")
        self.assertEqual(result.returncode, 0)

    def test_remote_command_failure_is_not_treated_as_connection_error(self):
        result = self.run_wrapper("sh", "-c", "exit 1")

        self.assertEqual(result.stdout, "")
        self.assertEqual(result.returncode, 1)

    def test_arguments_reach_the_command_unchanged(self):
        result = self.run_wrapper("printf", "%s|", "a b", "$(id)", "'")

        self.assertEqual(result.stdout, "a b|$(id)|'|")


class RecordingPopen:
    def __init__(self, error: OSError | None = None):
        self.calls = []
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error:
            raise self.error


class LaunchTest(unittest.TestCase):
    def test_starts_detached_process_with_merged_environment(self):
        popen = RecordingPopen()

        launch(Command(argv=["kitty", "x"], env={"SSH_WALLET_ID": "id-1"}), popen=popen)

        [(argv, kwargs)] = popen.calls
        self.assertEqual(argv, ["kitty", "x"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["env"]["SSH_WALLET_ID"], "id-1")
        self.assertEqual(kwargs["env"]["PATH"], os.environ["PATH"])

    def test_missing_kitty_raises_launch_error(self):
        popen = RecordingPopen(FileNotFoundError(2, "No such file", "kitty"))

        with self.assertRaises(LaunchError) as ctx:
            launch(Command(argv=["kitty"], env={}), popen=popen)

        self.assertIn("kitty", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
