"""The terminal front end: `kram-tui` (docs/TUI_SPEC.md §15.2) and `python3 -m kram.tui` from a source checkout."""
import argparse
import sys
from urllib.parse import unquote, urlparse

from .. import __version__
from ..i18n import _


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kram-tui", description=_("Kram, the package manager, in a terminal."))
    parser.add_argument("--version", action="version", version=f"kram-tui {__version__}")
    parser.add_argument("--upgradable", action="store_true", help=_("open on the packages with an upgrade"))
    parser.add_argument("file", nargs="?", metavar="FILE.rpm", help=_("install a package file"))
    return parser.parse_args(argv)


def file_path(argument: str) -> str:
    """The package file of `kram-tui FILE.rpm`; a file: URL (a file manager's "Open with") as its path, as the GUIs
    take it (kram.gtk.app.file_argument)."""
    if argument.startswith("file:"):
        return unquote(urlparse(argument).path)
    return argument


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.file:
        # the installer alone (§10.8), and Kram ends when it closes
        from .installer import InstallerApp  # after the arguments: --help and --version need no Textual
        InstallerApp(file_path(args.file)).run()
        return 0
    from .app import KramApp
    KramApp(upgradable=args.upgradable).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
