<img src="data/io.github.elmodos.Kram.svg" alt="" width="96" align="right">

# Kram

[![COPR build status](https://copr.fedorainfracloud.org/coprs/elmodos/Kram/package/kram/status_image/last_build.png)](https://copr.fedorainfracloud.org/coprs/elmodos/Kram/package/kram/)
[![COPR version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fcopr.fedorainfracloud.org%2Fapi_3%2Fpackage%3Fownername%3Delmodos%26projectname%3DKram%26packagename%3Dkram%26with_latest_succeeded_build%3DTrue&query=%24.builds.latest_succeeded.source_package.version&label=COPR&color=blue)](https://copr.fedorainfracloud.org/coprs/elmodos/Kram/)
[![Fedora 43 | 44 | 45 | Rawhide](https://img.shields.io/badge/Fedora-43%20%7C%2044%20%7C%2045%20%7C%20Rawhide-294172?logo=fedora&logoColor=white)](https://copr.fedorainfracloud.org/coprs/elmodos/Kram/)
[![Latest release](https://img.shields.io/github/v/tag/elmodos/kram?label=release&sort=semver)](https://github.com/elmodos/kram/tags)
[![License: MIT](https://img.shields.io/github/license/elmodos/kram)](LICENSE)
[![Translations: 13 languages](https://img.shields.io/badge/translations-13%20languages-2ea44f)](docs/TRANSLATING.md)

A Synaptic-style package manager for Fedora: the full package list, checkboxes, statuses and origins,
search that works, and nothing happens until you press **Apply**.

Built on libdnf5 (the same library as `dnf5`) and Qt 6.

![Kram's main window: every package with its status, origin, versions, size and repository, filters on the
left, the selected package's details below](docs/screenshots/main.png)

| Review before applying | Check a downloaded .rpm | Ready for the next Fedora? |
|---|---|---|
| [![The review of the changes, with the equivalent dnf5 command](docs/screenshots/apply-preview.png)](docs/guide/applying-changes.md) | [![The installer for a downloaded .rpm file](docs/screenshots/install-file.png)](docs/guide/rpm-files.md) | [![What moving to Fedora 45 would do](docs/screenshots/fedora-release-result.png)](docs/guide/fedora-release.md) |

## Features

- **Every package in one table**, installed or not: status, origin (Fedora, COPR, third-party, local),
  versions, repository, size. [The package list](docs/guide/package-list.md)
- **Filters and search**: by status, origin, repository and group, your own custom filters ("unneeded
  dependencies over 50 MB"), search ranked by relevance. [Filters](docs/guide/package-list.md#filters)
- **Mark first, apply later**: install, upgrade, reinstall, downgrade to a chosen version, remove; choose
  which recommended packages to take; review the whole transaction and the equivalent `dnf5` command.
  [Marking and applying](docs/guide/applying-changes.md)
- **Downloaded .rpm files**, checked before installing: signature, root scripts, dependencies, a newer
  version in a repository. [Installing a file](docs/guide/rpm-files.md)
- **Repositories and COPR**: enable, disable and remove them, search Copr. [Repositories and
  COPR](docs/guide/repositories.md)
- **A new Fedora release**: what blocks the upgrade, what it would remove, the disk space it needs.
  [Fedora release](docs/guide/fedora-release.md)
- **Package cache**: what the caches take, including what Discover and GNOME Software left behind, and
  cleaning them. [Package cache](docs/guide/package-cache.md)
- **Tray icon while updates are available** (optional, off by default), without any background downloads.
  [Update notifications](docs/guide/update-notifications.md)
- **One password per session** (polkit); browsing and searching need none.
- **In 13 languages**. [Translations](docs/TRANSLATING.md)

## User guide

What each part of Kram does, with screenshots:

- [The package list](docs/guide/package-list.md): the table, the sidebar filters, search and the package
  details.
- [Marking and applying changes](docs/guide/applying-changes.md): marking packages, reviewing the
  transaction, the progress window and key import.
- [Installing a downloaded .rpm file](docs/guide/rpm-files.md): what Kram checks before installing a file.
- [Repositories and COPR](docs/guide/repositories.md): enabling repositories and COPR projects, searching
  Copr.
- [A new Fedora release](docs/guide/fedora-release.md): what moving to the next release would do.
- [Package cache](docs/guide/package-cache.md): what the caches take and how to clean them.
- [Update notifications](docs/guide/update-notifications.md): the optional tray icon.

## Installing

From COPR:

```sh
sudo dnf copr enable elmodos/Kram
sudo dnf install kram
```

To build the RPM yourself, or to run Kram from a checkout, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing

Issues and pull requests are welcome: [CONTRIBUTING.md](CONTRIBUTING.md) for code,
[docs/TRANSLATING.md](docs/TRANSLATING.md) for translations, [docs/PLAN.md](docs/PLAN.md) for the design.

## License

Kram is released under the [MIT License](LICENSE).

SPDX-License-Identifier: MIT
