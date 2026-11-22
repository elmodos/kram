# Contributing to Kram

Bug reports, ideas and pull requests are welcome in the [issues](https://github.com/elmodos/kram/issues).
Translations have their own page: [docs/TRANSLATING.md](docs/TRANSLATING.md). The design and its reasoning are in
[docs/PLAN.md](docs/PLAN.md).

## Running from a checkout

Tested on Fedora 44 with KDE Plasma; any Qt-friendly desktop should work:

```sh
sudo dnf install python3-libdnf5 python3-rpm python3-pyside6 polkit gettext
python3 -m kram.qt
python3 -m kram.qt ~/Downloads/some-package.rpm   # only the installer for that file
```

The GTK 4 + libadwaita front end (in progress on the `feature/gtk` branch, see
[docs/GTK_FRONTEND.md](docs/GTK_FRONTEND.md)) needs libadwaita 1.7 or newer (Fedora 43 and later) instead of
PySide6:

```sh
sudo dnf install python3-libdnf5 python3-rpm python3-gobject gtk4 libadwaita polkit gettext
python3 -m kram.gtk
```

Browsing and searching need no privileges. Applying changes or refreshing metadata asks for the
administrator password once per session (through `pkexec`).

## Tests and checks

```sh
python3 -m pytest          # unit tests (needs pytest; gettext for the translation tests; PySide6 for the Qt
                           # tests, gtk4 and libadwaita for the GTK ones, which start their own broadway display)
ruff check .
scripts/container_check.sh # real root transactions in a throwaway Fedora container (podman)
scripts/rpm_check.sh       # build the RPM like COPR does, install it and check it, in a container
```

## Layout

- `kram/core/`, `kram/ipc/`, `kram/helper/` and `kram/notifier/` import no Qt; `kram/core/` is where most
  logic and tests live. The backend reaches the GUI only through `kram.core.mainloop` (a `post` function that
  runs a callable on the GUI thread, and a plain `Signal`); `kram/qt/qt_loop.py` is Qt's `post`.
- `kram/helper/kram_helper.py` is the only code that runs as root. Keep it small; it is the security
  boundary.
- All libdnf5 calls in the GUI process happen on one worker thread (`kram/core/worker.py`).
- User-visible strings are English in the code and translated with gettext; see
  [docs/TRANSLATING.md](docs/TRANSLATING.md#for-developers).

## Front ends

Kram has one toolkit-free layer and several front ends over it, so that a new one (a second GUI, a terminal
interface, or something remote) does not start from zero:

- `kram/core/` and `kram/app/` import no GUI toolkit (`tests/test_toolkit_free.py` checks it). The logic lives
  there: the package list and its sorting, marks, search, details, the dialogs' flows, the helper's requests.
- A front end only draws and forwards. Qt is in `kram/qt/`, GTK 4 and libadwaita in `kram/gtk/`.
- What each front end supports is listed in `kram/app/parity.py`, and explained in
  [docs/PARITY.md](docs/PARITY.md). A front end that is not released yet may have `PLANNED` features; a released one
  may not.

Nothing here makes a remote or web front end, and none is planned. The layering is there so that one could be added
without rewriting the logic.

## Building the RPM

The same steps COPR runs:

```sh
sudo dnf install rpm-build make git-core 'dnf5-command(builddep)'
make -f .copr/Makefile srpm outdir=/tmp/kram
sudo dnf builddep /tmp/kram/kram-*.src.rpm
rpmbuild --rebuild /tmp/kram/kram-*.src.rpm
sudo dnf install ~/rpmbuild/RPMS/noarch/kram-*.noarch.rpm
```

The package installs the root helper as `/usr/libexec/kram-helper` with its own polkit action
(`io.github.elmodos.Kram.helper`), the `.desktop` file, AppStream metadata and the translations.

## Packaging and COPR

- `packaging/kram.spec` is the RPM spec; `data/` has the `.desktop` file, AppStream metainfo, polkit policy
  and icon, all named after the app id `io.github.elmodos.Kram` (`kram/__init__.py`).
- How the COPR project builds and how a release is made: [docs/COPR.md](docs/COPR.md).
- `.copr/Makefile` builds an SRPM from the current commit: a plain release for the commit tagged
  `v<version>`, a `<version>^YYYYMMDDHHMMSSgitHASH` snapshot for any other commit.
- A release: bump the version (see [docs/COPR.md](docs/COPR.md#releases)), tag `v<version>`, push the tag and
  point the COPR package's Committish at it.

## Screenshots

`docs/screenshots/` holds the screenshots of the README and the [user guide](README.md#user-guide). The AppStream
metainfo links some of them by URL on `main` (Discover and GNOME Software show them), so keep their file names:
replace a file in place rather than renaming it.
