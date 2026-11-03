# Kram

A Synaptic-style package manager for Fedora: the full package list, checkboxes, statuses and origins,
search that works, and nothing happens until you press **Apply**.

Built on libdnf5 (the same library as `dnf5`) and Qt 6. Work in progress — see [docs/PLAN.md](docs/PLAN.md).

## Running from a checkout

Tested on Fedora 44 with KDE Plasma; any Qt-friendly desktop should work:

```sh
sudo dnf install python3-libdnf5 python3-rpm python3-pyside6 polkit gettext
python3 -m kram
```

Browsing and searching need no privileges. Applying changes or refreshing metadata asks for the
administrator password once per session (through `pkexec`).

## Development

```sh
python3 -m pytest          # unit tests (needs pytest; gettext for the translation tests)
ruff check .
scripts/container_check.sh # real root transactions in a throwaway Fedora container (podman)
```

- `kram/core/` has no Qt and is where most logic and tests live.
- `kram/helper/kram_helper.py` is the only code that runs as root. Keep it small; it is the security
  boundary.
- All libdnf5 calls in the GUI process happen on one worker thread (`kram/ui/dnf_thread.py`).

## Translations

User-visible strings are English in the code and translated with gettext:

```python
from kram.i18n import _, ngettext, pgettext, N_

_("Reload")
ngettext("{n} package", "{n} packages", n).format(n=n)   # plurals
pgettext("package status", "Installed")                   # same English word, different translations
```

Use named `{placeholders}` with `.format()`, never f-strings inside `_()`.

- Update the template and all catalogs after changing strings: `scripts/i18n.sh update`
- Start a new language: `scripts/i18n.sh new de`, then translate `po/de.po`
- Validate: `scripts/i18n.sh check` (the test suite also checks that the template is current, catalogs
  are complete, and placeholders match)

The language follows the environment, e.g. `LANGUAGE=uk python3 -m kram`.

## License

Kram is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either version 3 of the License, or (at your option)
any later version. See [LICENSE](LICENSE).

SPDX-License-Identifier: GPL-3.0-or-later
