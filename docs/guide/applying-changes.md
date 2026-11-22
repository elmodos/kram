# Marking and applying changes

Nothing happens to the system until you press **Apply**. Until then Kram only collects what you marked.

## Marking

Click a package's status box (the S column), or use the Package menu or the context menu, and mark it for
installation, upgrade, reinstallation, downgrade to a version you choose, or removal. You can also change its
install reason: installed by you, or a dependency. **Mark All Upgrades** marks every package that has a newer
version. The arrow next to it (and Edit → Mark Upgrades) marks only some of them, by their
[update type](package-list.md#update-types): the security upgrades, as `dnf upgrade --security` does; only
the security upgrades rated critical or important; or the security and bug fix upgrades, without the
enhancements. Upgrades from repositories without advisories are in none of these.

**Edit → Mark Unneeded Dependencies for Removal** does what `dnf autoremove` does: it marks for removal every
package that was installed as a dependency and that nothing needs any more (the *Unneeded dependencies* status
filter lists them; its context menu has the same item). The review shows them all before anything is removed;
mark a package as installed by you to keep it.

Double-clicking a package marks it for installation or upgrade, or unmarks it if it is already marked. With
Settings → *Clicking the status icon marks the likely action* on, a single click on the status box does the
same instead of opening the menu, as in Synaptic.

The markings can be saved to a file and read back later (File menu), for example to set up a second
computer the same way.

When a package you mark for installation conflicts with an installed one, *Apply* says which installed packages
stand in the way and offers to mark them for removal, as Synaptic does, and then shows the review of both. That
is what `dnf swap` does: switching `ffmpeg-free` for `ffmpeg` from RPM Fusion, or Kram's own Qt front end for
the GTK one (`kram-qt` for `kram-gtk`). Kram offers it only when removing them is all it takes, not when dnf
would also have to swap or downgrade other packages. When the removal takes the front end of Kram you are using,
Kram says so before, and closes after the changes are applied; start it again.

## Reviewing the transaction

![The Apply changes window with four upgrades, the sizes, and the equivalent dnf5
command](../screenshots/apply-preview.png)

*Before anything happens: every change with its version and size, what it downloads, the disk space it
takes, and the `dnf5` command that would do the same.*

The review lists the marked packages (or the group you install or remove from the sidebar) and everything dnf
adds for them, grouped by what happens to them. When a package recommends others, each recommendation gets its own checkbox with the size it adds, so you
choose which ones to install. *Download packages only* fetches the packages without installing them.
If the disk is too full for the transaction, the review says how much space is missing and on which filesystem,
and *Apply* stays off; when the download alone fits, *Download packages only* can still fetch the packages.
Packages already downloaded are not counted again.

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
