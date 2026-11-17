#!/usr/bin/python3
"""How fast Kram's catalog and searches are on this machine, and how long the window stops responding meanwhile.

    python3 scripts/perf_search.py

Runs the real main window from this checkout, offscreen and with settings of its own (the user's are not touched).
Reads the system's dnf cache like Kram does: no root, no network, nothing on the system changes. "Frozen" is the
longest time the window's event loop could not run: what the user feels as a hang.
"""
import os
import platform
import resource
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

TYPED = ("kernel-devel", "python3-requests", "libreoffice")
PROVIDES = ("python3dist(requests)", "vulkan", "lib", "python3dist(*)", "webbrowser", "application()")


def machine() -> str:
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), platform.processor() or "?")
    mem = next((int(line.split()[1]) // 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemTotal")), 0)
    return f"{cpu}, {os.cpu_count()} threads, {mem} MB RAM, Python {platform.python_version()}"


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("kram-perf")
    app.setApplicationName("kram-perf")
    from kram.core.search import Mode
    from kram.ui.main_window import MainWindow

    def pump(done, limit: float = 600) -> tuple[float, float]:
        """Run the event loop until `done()`: (seconds taken, longest gap between two turns of the loop)."""
        start = last = time.perf_counter()
        worst = 0.0
        while not done() and time.perf_counter() - start < limit:
            app.processEvents()
            time.sleep(0.002)
            now = time.perf_counter()
            worst, last = max(worst, now - last), now
        return time.perf_counter() - start, worst

    print(machine())
    window = MainWindow()
    window.show()
    took, frozen = pump(lambda: window.snapshot is not None)
    print(f"\ncatalog load            {took:6.2f} s   frozen {frozen:5.2f} s   {len(window.snapshot.rows)} rows")

    print("\nsearch by name and summary, typed one character at a time (ms per character)")
    window.search_mode.setCurrentIndex(Mode.NAME_SUMMARY)
    for word in TYPED:
        times = []
        for n in range(1, len(word) + 1):
            window.search.setText(word[:n])
            start = time.perf_counter()
            window.apply_filter()
            times.append((time.perf_counter() - start) * 1000)
        print(f"  {word:20} worst {max(times):6.1f}  total {sum(times):7.1f}   "
              + " ".join(f"{t:.0f}" for t in times))
    window.search.setText("")
    start = time.perf_counter()
    window.apply_filter()
    print(f"  {'(empty: all rows)':20} {(time.perf_counter() - start) * 1000:6.1f}")

    print("\npackage details, as when the cursor lands on a package (the first also learns what is required)")
    for key in (("kernel-core", window.snapshot.basearch), ("kernel-modules", window.snapshot.basearch),
                ("glibc", window.snapshot.basearch), ("bash", window.snapshot.basearch)):
        if window.key_index.get(key) is None or not window.snapshot.rows[window.key_index[key]].installed:
            continue
        answer = []
        window.dnf.submit(lambda key=key: window.catalog.details(key), answer.append, answer.append)
        took, frozen = pump(lambda: bool(answer))
        print(f"  {key[0]:24} {took:6.2f} s   frozen {frozen:5.2f} s")

    print("\nProvides (the first search by part of a name or with * also builds the index)")
    for text in PROVIDES:
        answer = []
        window.dnf.submit(lambda text=text: window.catalog.search_provides(text), answer.append, answer.append)
        took, frozen = pump(lambda: bool(answer))
        hits = len(answer[0]) if isinstance(answer[0], list) else answer[0]
        print(f"  {text:24} {took:6.2f} s   frozen {frozen:5.2f} s   {hits} packages")

    print(f"\npeak memory {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB")
    sys.stdout.flush()
    os._exit(0)  # skip tearing down 70k rows of Qt objects


if __name__ == "__main__":
    sys.exit(main())
