"""The terminal front end: `kram-tui` (docs/TUI_SPEC.md §15.2) and `python3 -m kram.tui` from a source checkout."""
import argparse
import sys

from .. import __version__
from ..i18n import _


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kram-tui", description=_("Kram, the package manager, in a terminal."))
    parser.add_argument("--version", action="version", version=f"kram-tui {__version__}")
    parser.add_argument("--upgradable", action="store_true", help=_("open on the packages with an upgrade"))
    parser.add_argument("file", nargs="?", metavar="FILE.rpm", help=_("install a package file"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.file:
        # the installer alone (§10.8) comes with the dialogs; not translated, as it goes with them
        print("kram-tui: installing a package file comes in a later version", file=sys.stderr)
        return 2
    from .app import KramApp  # after the arguments: --help and --version need no Textual
    KramApp(upgradable=args.upgradable, file=args.file).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
