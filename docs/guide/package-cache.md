# Cleanup

Settings → Cleanup… shows what the package caches take, where they are, and cleans them. Below them it lists
the leftover configuration files rpm keeps.

![The Package Cache window: dnf's downloaded packages, repository metadata, your user's dnf cache, and 3.3 GB
left behind by Discover and GNOME Software](../screenshots/package-cache.png)

*Each cache with its size and folder. Here the biggest one is not dnf's: Discover left 3.3 GB of offline
updates behind.*

- **DNF: downloaded packages**: left by interrupted transactions and by "download packages only".
- **DNF: repository metadata**: what Kram and dnf know about the available packages. Kram can download it
  again from scratch.
- **DNF: cache of your user**: written by dnf when it runs without root. Kram does not use it.
- **Discover / GNOME Software**: packages PackageKit downloaded for offline updates and never removed.

## Leftover configuration files

When an update brings a new version of a configuration file you have changed, rpm does not overwrite your
version: it puts the package's new default beside it as `<file>.rpmnew`. When it does replace or remove a file you
had changed, it keeps your version as `<file>.rpmsave` (or `.rpmorig`). Nothing reads these copies, and nothing
removes them.

- **A copy of a file that no longer exists** (for example `/etc/yum.repos.d/fedora.repo.rpmsave` after Fedora
  moved its repositories to `/usr/share/dnf5/repos.d`): nothing uses it. *Delete Unused…* removes all of them.
- **Your earlier version** (`.rpmsave`): *Compare* shows what you had changed; take over what you still want,
  then delete it.
- **A package's new default** (`.rpmnew`): not applied. *Compare* shows what the package changed, often a new
  option or a security default; merge what you need into your file, then delete the copy.

Kram searches the folders you can read without a password. Some of `/etc` only root can read (`firewalld`,
`sudoers.d`, `polkit-1/rules.d`…): *Search All Folders…* searches them too, after the password. Files only root
can read cannot be compared in Kram; the button's tooltip gives the `sudo diff` command for a terminal.

Next: [Update notifications](update-notifications.md).
