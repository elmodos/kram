#!/bin/bash
# The test run of .github/workflows/tests.yml, as root in a Fedora container: install what the tests need, then ruff,
# the parity check and the whole suite. The same locally, on any release:
#   podman run --rm -v "$PWD:/src:Z" -w /src registry.fedoraproject.org/fedora:44 bash scripts/ci_tests.sh
set -euo pipefail

echo "### Fedora $(rpm -E %fedora), packages"
# what tests/ imports and calls: libdnf5 and rpm, both front ends' toolkits (GTK through its broadway display server,
# in gtk4), gettext for the catalogs, the desktop file and AppStream checkers
dnf5 -y -q install python3-libdnf5 python3-rpm python3-pytest python3-pyside6 python3-gobject gtk4 libadwaita \
    gettext libglvnd-egl fontconfig desktop-file-utils libappstream-glib ruff >/dev/null
rpm -q --qf '%{name}-%{version}\n' python3 python3-libdnf5 python3-pyside6 gtk4 libadwaita ruff

echo "### the modules the tests would otherwise skip"
# tests/ skip a module that is missing (pytest.importorskip): here that would hide a whole front end
python3 - <<'EOF'
import libdnf5, rpm  # noqa: F401
from PySide6 import QtCore, QtWidgets  # noqa: F401
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402
assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 7), "libadwaita >= 1.7 (Adw.ToggleGroup)"
print("libdnf5, rpm, PySide6, GTK 4 and libadwaita", f"{Adw.get_major_version()}.{Adw.get_minor_version()}")
EOF

export QT_QPA_PLATFORM=offscreen
echo "### ruff"
ruff check .
echo "### parity (kram/app/parity.py)"
python3 -m pytest -q tests/test_parity.py
echo "### pytest"
python3 -m pytest -q -rs
