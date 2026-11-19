# The package list

![The main window: the sidebar filters on the left, the package table on the right, the details of the
selected package below](../screenshots/main.png)

*The main window. Kram, installed from COPR, is selected; its details are on the General tab.*

## The table

Every package of the enabled repositories is in one table, installed or not: its status, origin, name, latest
and installed version, update type, size, repository and summary. Browsing and searching need no password.

The origin icon tells where a package comes from: Fedora, a COPR project, a third-party repository, or a
local file with no repository at all.

*File → Export List as CSV…* saves the packages listed now, in their order, to a CSV file for a spreadsheet or
a script. It has the same columns in every language, whatever the table shows: name, arch, status, the
installed and latest version, the repository, origin, install reason, update type and advisories, the size in
bytes, the summary and the marking, if any.

The Repository column says where the latest version comes from. When an installed package came from another
repository, that one comes first: `elmodos/Kram → updates` is a COPR package whose newer version is now in
Fedora's updates.

## Update types

For a package with an upgrade, a coloured dot before the latest version and the **Update type** column tell
what the upgrade is, by the advisories Fedora publishes with its updates:

- red and orange: a security fix, rated critical, important, moderate or low;
- blue: a bug fix;
- grey: an enhancement or anything else.

The tooltip lists every advisory of the upgrade, and the **Advisories** tab under the table shows them in
full: what they fix, and links to the advisory on Bodhi and to the bugs and CVEs. The tab is there only for
packages with advisories, with a dot of the same colour in its title. When several versions came out since the installed
one, all of their advisories count: a security fix in one of them is shown even when the newest is only a bug
fix. Repositories that publish no advisories (RPM Fusion, COPR, most third-party ones) leave both empty.
Sorting by the column puts the most important upgrades first; right-click the table header to hide it.

## Filters

The sidebar on the left narrows the table. The buttons at its bottom switch between groups of filters:

- **Status**: all, installed, not installed, upgradable (and below it the security updates and the bug fix
  updates), installed by you, unneeded dependencies, orphaned (installed but in no repository), newer than the
  repository, marked.
- **Origin**: Fedora, COPR, third-party, local; under each, every repository on its own.
- **Groups**: the comps groups; installed ones are in bold. Right-click a group to mark it for installation,
  or an installed one for upgrade or removal, as `dnf5 group install`, `upgrade` and `remove` do. Installing a
  group brings its mandatory and default packages; removing it removes the packages it brought, unless you
  installed them yourself or something else needs them.
- **Search results**: your earlier searches, to go back to one.
- **Custom filters**: your own filters. A filter combines name, summary, description, provided capability,
  status, origin, repository, group, install reason, architecture, size and update type. For example
  "installed by user from COPR", "unneeded dependencies over 50 MB", or, with `application()`, only what has a
  menu entry.
  Settings → New Filter from Current View… starts one from what the table shows.

## Search

Search (Ctrl+F) ranks results by relevance. The drop-down next to it chooses what to search: the name, the
name and summary, the description, a provided capability, or a file.

When nothing is found, the empty list says why and offers what would help: the same search in *All* when a
sidebar filter hid the results, a search of the descriptions when the name gave nothing, and Reload when some
repositories have no metadata, so their packages are missing.

## Package details

The tabs under the table show the selected package: its description, general information (origin,
repository, license, install reason, sizes), the advisories of an upgrade, its dependencies (each one
clickable), its files, every available version and the changelog.

The Files tab shows the files in their folders, every folder open, or as a list of full paths (the buttons
next to the filter switch between them). The filter field keeps the files with the text anywhere in their path,
or the ones matching a pattern such as `*.so*`, `libfoo*` or `/usr/bin/*`; what it matched is in bold, so a
file that is there only because of its folder's name is easy to tell. It stays when you select another
package, to look for the same file there. Right-click a file to copy its path or, for an installed package, to
show it in the file manager.

Next: [Marking and applying changes](applying-changes.md).
