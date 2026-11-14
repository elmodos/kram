# The package list

![The main window: the sidebar filters on the left, the package table on the right, the details of the
selected package below](../screenshots/main.png)

*The main window. Kram, installed from COPR, is selected; its details are on the General tab.*

## The table

Every package of the enabled repositories is in one table, installed or not: its status, origin, name, latest
and installed version, size, repository and summary. Browsing and searching need no password.

The origin icon tells where a package comes from: Fedora, a COPR project, a third-party repository, or a
local file with no repository at all.

## Filters

The sidebar on the left narrows the table. The buttons at its bottom switch between groups of filters:

- **Status**: all, installed, not installed, upgradable, installed by you, unneeded dependencies, orphaned
  (installed but in no repository), newer than the repository, marked.
- **Origin**: Fedora, COPR, third-party, local; COPR projects and third-party repositories each on their own.
- **Groups**: the comps groups.
- **Search results**: your earlier searches, to go back to one.
- **Custom filters**: your own filters. A filter combines name, summary, description, provided capability,
  status, origin, repository, group, install reason, architecture and size. For example "installed by user
  from COPR", "unneeded dependencies over 50 MB", or, with `application()`, only what has a menu entry.
  Settings → New Filter from Current View… starts one from what the table shows.

## Search

Search (Ctrl+F) ranks results by relevance. The drop-down next to it chooses what to search: the name, the
name and summary, the description, a provided capability, or a file.

## Package details

The tabs under the table show the selected package: its description, general information (origin,
repository, license, install reason, sizes), its dependencies (each one clickable), its files, every
available version and the changelog.

Next: [Marking and applying changes](applying-changes.md).
