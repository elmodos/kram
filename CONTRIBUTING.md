# Contributing to Kram

Bug reports, ideas and pull requests are welcome in the [issues](https://github.com/elmodos/kram/issues).
Translations have their own page: [docs/TRANSLATING.md](docs/TRANSLATING.md). The design and its reasoning are in
[docs/PLAN.md](docs/PLAN.md).

## Running from a checkout

Tested on Fedora 44 with KDE Plasma; any Qt-friendly desktop should work:

```sh
sudo dnf install python3-libdnf5 python3-rpm python3-pyside6 polkit gettext
python3 -m kram
python3 -m kram ~/Downloads/some-package.rpm   # only the installer for that file
```

Browsing and searching need no privileges. Applying changes or refreshing metadata asks for the
administrator password once per session (through `pkexec`).

## Tests and checks

```sh
python3 -m pytest          # unit tests (needs pytest; gettext for the translation tests)
ruff check .
scripts/container_check.sh # real root transactions in a throwaway Fedora container (podman)
scripts/rpm_check.sh       # build the RPM like COPR does, install it and check it, in a container
```

## Layout

- `kram/core/` has no Qt and is where most logic and tests live.
- `kram/helper/kram_helper.py` is the only code that runs as root. Keep it small; it is the security
  boundary.
- All libdnf5 calls in the GUI process happen on one worker thread (`kram/ui/dnf_thread.py`).
- User-visible strings are English in the code and translated with gettext; see
  [docs/TRANSLATING.md](docs/TRANSLATING.md#for-developers).

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
