# Marking and applying changes

Nothing happens to the system until you press **Apply**. Until then Kram only collects what you marked.

## Marking

Click a package's status box (the S column), or use the Package menu or the context menu, and mark it for
installation, upgrade, reinstallation, downgrade to a version you choose, or removal. You can also change its
install reason: installed by you, or a dependency. **Mark All Upgrades** marks every package that has a newer
version.

Double-clicking a package marks it for installation or upgrade, or unmarks it if it is already marked. With
Settings → *Clicking the status icon marks the likely action* on, a single click on the status box does the
same instead of opening the menu, as in Synaptic.

The markings can be saved to a file and read back later (File menu), for example to set up a second
computer the same way.

## Reviewing the transaction

![The Apply changes window with four upgrades, the sizes, and the equivalent dnf5
command](../screenshots/apply-preview.png)

*Before anything happens: every change with its version and size, what it downloads, the disk space it
takes, and the `dnf5` command that would do the same.*

The review lists the marked packages and everything dnf adds for them, grouped by what happens to them. When
a package recommends others, each recommendation gets its own checkbox with the size it adds, so you choose
which ones to install. *Download packages only* fetches the packages without installing them.

## Applying

![The Applying changes window: download progress and a log of the
transaction](../screenshots/progress.png)

*Downloading and installing, with a log of each step.*

The first change in a session asks for the administrator password (polkit); later ones in the same session
do not. The work is done by a small helper that runs as root; the rest of Kram runs as you.

![The Import key question over the progress window, with the key's user, fingerprint and
source](../screenshots/key-import.png)

*A repository's signing key is imported only after you have seen who it belongs to and where it comes from.*

Next: [Installing a downloaded .rpm file](rpm-files.md).
