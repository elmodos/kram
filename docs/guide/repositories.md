# Repositories and COPR

**Repositories** (Settings menu or toolbar) enables and disables the configured repositories.

- *Show packages* filters the main table to a repository's packages.
- *Remove…* deletes a repository you added yourself: its `.repo` file in `/etc/yum.repos.d`. When the file
  configures several repositories (often with `-debuginfo` and `-source` ones), they all go, and the confirmation
  lists them. Packages installed from them stay installed, without updates.
- Repositories that a package brought (Fedora's own, RPM Fusion, `fedora-workstation-repositories`) are not
  removed: the package would bring them back with its next update. Disable them, or remove that package. The
  same goes for repositories the system configures outside `/etc/yum.repos.d`.

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

Next: [A new Fedora release](fedora-release.md).
