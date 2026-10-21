import os
import shlex
import subprocess
import unittest
from pathlib import Path

from ssh_wallet.launcher import WRAPPER, Command, LaunchError, build_command, display_command, launch
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



class JumpTest(unittest.TestCase):
    target = Host(name="pks2", host="2001:db8::1", user="student", id="id-2", jump_id="id-1")

    def test_jump_goes_through_proxy_command_before_destination(self):
        jump = Host(name="bastion", host="bastion.example", user="admin", port=2222, id="id-1")

        command = build_command(self.target, has_password=False, askpass_path=ASKPASS, jump=jump)

        self.assertEqual(ssh_part(command), [
            "ssh", "-p", "22",
            "-o", "ProxyCommand=ssh -W '[%h]:%p' -p 2222 -- admin@bastion.example",
            "--", "student@2001:db8::1",
        ])

    def test_jump_key_is_quoted_and_percent_escaped(self):
        jump = Host(name="b", host="b", user="u$(id)", key_path="~/.ssh/my key%1", id="id-1")

        command = build_command(self.target, has_password=False, askpass_path=ASKPASS, jump=jump)

        key = str(Path.home() / ".ssh/my key%%1")
        self.assertIn(
            f"ProxyCommand=ssh -W '[%h]:%p' -p 22 -i '{key}' -o IdentitiesOnly=yes -- 'u$(id)@b'",
            ssh_part(command),
        )

    def test_jump_password_is_announced_to_askpass(self):
        jump = Host(name="b", host="bastion.example", id="id-1")

        command = build_command(self.target, has_password=True, askpass_path=ASKPASS,
                                jump=jump, jump_has_password=True)

        self.assertEqual(command.env, {
            "SSH_ASKPASS": "/opt/wallet/bin/ssh-wallet-askpass",
            "SSH_ASKPASS_REQUIRE": "force",
            "SSH_WALLET_ID": "id-2",
            "SSH_WALLET_JUMP_ID": "id-1",
            "SSH_WALLET_JUMP_HOST": "bastion.example",
        })

    def test_only_jump_has_password(self):
        jump = Host(name="b", host="bastion.example", id="id-1")

        command = build_command(self.target, has_password=False, askpass_path=ASKPASS,
                                jump=jump, jump_has_password=True)

        self.assertNotIn("SSH_WALLET_ID", command.env)
        self.assertEqual(command.env["SSH_WALLET_JUMP_ID"], "id-1")


class DisplayCommandTest(unittest.TestCase):
    """The ssh command copied for the user: short, but runnable in a shell."""

    def test_plain_host_without_default_port(self):
        self.assertEqual(display_command(Host(name="m", host="192.168.122.19", user="admin")),
                         "ssh admin@192.168.122.19")

    def test_port_and_key_keep_the_tilde(self):
        host = Host(name="nas", host="nas", user="kuba", port=2222, key_path="~/.ssh/nas_key")

        self.assertEqual(display_command(host), "ssh -p 2222 -i ~/.ssh/nas_key kuba@nas")

    def test_key_with_spaces_is_quoted_after_the_tilde(self):
        host = Host(name="nas", host="nas", key_path="~/my keys/nas")

        self.assertEqual(display_command(host), "ssh -i ~/'my keys/nas' nas")

    def test_absolute_key_and_destination_are_shell_quoted(self):
        host = Host(name="nas", host="nas", user="ku$ba", key_path="/keys/a b")

        self.assertEqual(display_command(host), "ssh -i '/keys/a b' 'ku$ba@nas'")

    def test_jump_without_key_uses_dash_j(self):
        jump = Host(name="bastion", host="bastion.example", user="admin", port=2200)
        host = Host(name="pks2", host="10.0.0.6", user="student", jump_id=jump.id)

        self.assertEqual(display_command(host, jump), "ssh -J admin@bastion.example:2200 student@10.0.0.6")

    def test_jump_on_default_port_and_ipv6_jump(self):
        host = Host(name="pks2", host="10.0.0.6")

        self.assertEqual(display_command(host, Host(name="b", host="bastion")), "ssh -J bastion 10.0.0.6")
        self.assertEqual(display_command(host, Host(name="b", host="2001:db8::2", user="a", port=2200)),
                         "ssh -J 'a@[2001:db8::2]:2200' 10.0.0.6")

    def test_jump_with_key_uses_proxy_command(self):
        jump = Host(name="bastion", host="bastion", user="admin", key_path="/keys/b")
        host = Host(name="pks2", host="10.0.0.6")

        command = display_command(host, jump)

        self.assertEqual(shlex.split(command), [
            "ssh", "-o", "ProxyCommand=ssh -W '[%h]:%p' -p 22 -i /keys/b -o IdentitiesOnly=yes -- admin@bastion",
            "10.0.0.6",
        ])


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
