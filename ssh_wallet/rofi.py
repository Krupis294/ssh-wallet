"""Quick host picker in rofi: choose a host, get a kitty window with ssh.

Rows are fed to ``rofi -dmenu`` with the ``display`` row option: rofi renders
the Pango markup but filters on the plain ``search`` text (name, address and
note), so typing never matches markup tags. rofi returns the row index.
"""

import argparse
import html
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ssh_wallet.launcher import Command, LaunchError, launch
from ssh_wallet.model import Host

ROOT = Path(__file__).resolve().parent.parent
THEME_PATH = ROOT / "data" / "ssh-wallet.rasi"
GUI_PATH = ROOT / "bin" / "ssh-wallet"
GUI_ENTRY = "otevřít ssh-wallet"

_CONTROL = re.compile(r"[\n\r\0\x1f]+")


@dataclass
class Row:
    search: str
    display: str
    permanent: bool = False


def _dim(text: str) -> str:
    return f'<span alpha="60%">{html.escape(text, quote=False)}</span>'


def host_rows(hosts: list[Host], has_password) -> list[Row]:
    width = max((len(h.name) for h in hosts), default=0)
    rows = []
    for host in hosts:
        tags = [t for t, on in (("pw", has_password(host.id)), ("key", bool(host.key_path))) if on]
        display = (f"<b>{html.escape(host.name, quote=False)}</b>"
                   + " " * (width - len(host.name) + 2) + _dim(host.subtitle()))
        if tags:
            display += "  " + _dim(" ".join(tags))
        search = " ".join(part for part in (host.name, host.subtitle(), host.note) if part)
        rows.append(Row(" ".join(search.split()), display))
    return rows


def encode(rows: list[Row]) -> str:
    """rofi dmenu input: one line per row with ``\\0option\\x1fvalue`` options."""
    lines = []
    for row in rows:
        line = f"{_clean(row.search)}\0display\x1f{_clean(row.display)}"
        if row.permanent:
            line += "\x1fpermanent\x1ftrue"
        lines.append(line + "\n")
    return "".join(lines)


def _clean(text: str) -> str:
    return _CONTROL.sub(" ", text)


def rofi_command(theme: Path | None, mesg: str | None = None) -> list[str]:
    argv = ["rofi", "-dmenu", "-i", "-markup-rows", "-no-custom", "-format", "i", "-p", "ssh"]
    if theme:
        argv += ["-theme", str(theme)]
    if mesg:
        argv += ["-mesg", mesg]
    return argv


def parse_selection(result: subprocess.CompletedProcess) -> int | None:
    """Index of the chosen row, or None when rofi was cancelled."""
    choice = result.stdout.strip()
    if result.returncode != 0 or not choice.isdigit():
        return None
    return int(choice)


def run(wallet, rofi, theme: Path | None, open_gui) -> int:
    """``rofi(argv, input_text)`` runs rofi and returns a CompletedProcess."""
    backup = wallet.load()
    hosts = wallet.hosts
    rows = host_rows(hosts, wallet.has_password)
    rows.append(Row(GUI_ENTRY, f"<i>{GUI_ENTRY}</i>", permanent=True))

    mesg = None
    if backup:
        mesg = f"Soubor s hosty byl nečitelný, přesunut do {backup}."
    elif not hosts:
        mesg = "Zatím žádné hosty. Přidej je v ssh-wallet."

    index = parse_selection(rofi(rofi_command(theme, mesg), encode(rows)))
    if index is None:
        return 0
    if index >= len(hosts):
        open_gui()
        return 0
    try:
        wallet.connect(hosts[index])
    except LaunchError as e:
        argv = ["rofi", "-e", str(e)] + (["-theme", str(theme)] if theme else [])
        rofi(argv, "")
        return 1
    return 0


def _run_rofi(argv: list[str], text: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, input=text, capture_output=True, text=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ssh-wallet-rofi", description=__doc__.splitlines()[0])
    parser.add_argument("--system-theme", action="store_true",
                        help="use your rofi config instead of the bundled theme")
    args = parser.parse_args(argv)

    from ssh_wallet.store import HostStore, default_path
    from ssh_wallet.vault import SecretVault
    from ssh_wallet.wallet import Wallet

    # Like the other rofi menus: a second press of the shortcut replaces an open rofi.
    subprocess.run(["pkill", "-x", "rofi"], check=False)
    wallet = Wallet(HostStore(default_path()), SecretVault())
    return run(wallet, _run_rofi, None if args.system_theme else THEME_PATH,
               open_gui=lambda: launch(Command([str(GUI_PATH)])))
