# Repositories and COPR

**Repositories** (Settings menu or toolbar) enables and disables the configured repositories.

- *Show packages* filters the main table to a repository's packages.
- *Remove…* deletes a repository you added yourself: its `.repo` file in `/etc/yum.repos.d`. When the file
  configures several repositories (often with `-debuginfo` and `-source` ones), they all go, and the confirmation
  lists them. Packages installed from them stay installed, without updates.
- Repositories that a package brought (Fedora's own, RPM Fusion, `fedora-workstation-repositories`) are not
  removed: the package would bring them back with its next update. Disable them, or remove that package. The
  same goes for repositories the system configures outside `/etc/yum.repos.d`.
- The window stays open for what you do from it: a removal runs over it, *Mirrors…* opens over it, and the table
  then shows the new state. Only *Show packages* closes it, to show them in the main window.
- *Mirrors…* is for a repository that names a list of mirrors instead of one server, which is how Fedora's own
  repositories and RPM Fusion work. See below.

**COPR** manages COPR projects, the community repositories built on Fedora's Copr.

![The COPR repositories window: four enabled projects with their packages, and a search of Copr for
elmodos/kram](../screenshots/copr.png)

*Enabled COPR projects with how many of their packages you have installed; below, a search of Copr that shows
whether a project builds for this system.*

- Enable, disable or remove an enabled project; *Show packages* filters the main table to its packages.
- Search Copr by name or `owner/project` and enable what you find.

COPR projects are built by community members and are not reviewed by Fedora. The [package
list](package-list.md) shows COPR packages with their own origin icon, and the Origin filters list each
project.

## Mirrors

Fedora's repositories do not name a server: they name a *metalink*, a list of about twenty mirrors, and dnf
downloads from the first ones that answer. When those are slow, a metadata refresh takes minutes and nothing says
why. *Mirrors…* shows the list and measures it.

- The *Mirror* column of the table says which mirror each repository uses: *Automatic*, or the host of the mirror it
  is pinned to (the whole address is in the tooltip). In the Mirrors window the pinned mirror is in bold, marked
  *In use*.
- *Test Speed* asks every mirror for the repository's `repomd.xml` (the *Response* column), then downloads the
  first 2 MB of the largest metadata file from the quickest eight, one at a time (the *Speed* column). The fastest
  comes first when the test is done; *Stop Test* ends it earlier. A mirror whose copy of the repository is older
  than another's is marked *Out of date* and never counts as the fastest.
- *Use Selected Mirror* pins the repository to that mirror: Kram sets its `baseurl` to the mirror and empties its
  `metalink`, in `/etc/dnf/repos.override.d/99-config_manager.repo`, the file `dnf5 config-manager` writes. The
  metadata is downloaded again from the new mirror. The Mirrors window stays open over it, and then shows the
  mirror *In use*; the same goes for *Automatic* and the fastest-mirror button. Kram asks first about a mirror that is out of date or not
  reached over https.
- *Automatic* removes the pin, and the repository takes its mirrors from the list again. The same by hand:
  `dnf5 config-manager unsetopt updates.baseurl updates.metalink updates.mirrorlist`.
- *Turn On Fastest Mirror Search* sets dnf's own `fastestmirror` option for all repositories: dnf then tests the
  mirrors of a list itself before it downloads.

A pinned mirror is used for good: if it goes away or falls behind, the repository stops getting updates until you
choose another one or go back to *Automatic*. Without the metalink dnf cannot check that the mirror is current,
which is why the dialog shows which one is. Packages are signed either way. A repository with a single address
(most third-party ones, COPR) has no mirrors to choose from, and the button says so.

Next: [A new Fedora release](fedora-release.md).
