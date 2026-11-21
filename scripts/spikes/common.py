"""Shared by the GTK spikes (docs/GTK_FRONTEND.md §7.1): the catalog to show, and small measuring helpers.

The rows come from a pickled CatalogSnapshot when KRAM_SPIKE_SNAPSHOT names one (fast, and the same rows on every
run), else from a real `Catalog().load()` (read-only: it only reads the dnf cache), else from made-up rows.
"""
import os
import pickle
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


def snapshot():
    path = os.environ.get("KRAM_SPIKE_SNAPSHOT")
    if path and Path(path).exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    try:
        from kram.core.catalog import Catalog
        return Catalog().load()
    except Exception as e:  # noqa: BLE001 - no libdnf5 or no cache: made-up rows still answer the speed questions
        print(f"no catalog ({e}); using made-up rows", file=sys.stderr)
        return fake_snapshot()


def fake_snapshot(n: int = 70000):
    from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status
    rnd = random.Random(1)
    statuses = list(Status)
    rows = []
    for i in range(n):
        installed = rnd.random() < 0.05
        rows.append(PkgRow(name=f"package-{i:05d}-{rnd.choice('abcdefgh') * rnd.randint(1, 12)}",
                           arch=rnd.choice(("x86_64", "noarch", "i686")),
                           summary="A made-up package to fill the list " * rnd.randint(1, 3),
                           installed_evr="1.2.3-4.fc44" if installed else "", candidate_evr="1.2.4-1.fc44",
                           repo_id="fedora", size=rnd.randint(1000, 10**9), origin=Origin.FEDORA,
                           status=rnd.choice(statuses), download_size=rnd.randint(1000, 10**8)))
    return CatalogSnapshot(rows=rows, n_installed=0, n_upgradable=0, load_seconds=0)


def rss_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


class Stopwatch:
    def __init__(self):
        self.t = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self.t) * 1000


def versions() -> str:
    from gi.repository import Adw, GLib, Gtk
    return (f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}, "
            f"libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}, "
            f"PyGObject {gi.__version__}, GLib {GLib.MAJOR_VERSION}.{GLib.MINOR_VERSION}, "
            f"Python {sys.version.split()[0]}")
