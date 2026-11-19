# Transaction history

dnf records every transaction: what it installed, upgraded, downgraded and removed, when, and who ran it. Kram
shows that record, the same one `dnf5 history` reads, whether the change came from Kram, from `dnf` in a terminal,
from Discover or from GNOME Software. Reading it needs no password.

## Browsing

**File → Transaction History…** (Ctrl+H) opens a window with the transactions, the newest first: the date, what
changed ("2 installed, 12 upgraded"; "1 environment, 16 groups; …" when it also changed comps groups), the user and the command line (*Kram* for Kram's own). A transaction that failed
or did not finish has an error icon.

Below the list are the groups and environments of the selected transaction, then its packages, with what happened to each, the version (an upgrade
shows the old and the new one), the repository and the install reason. Double-click a package to close the window and
select the package in the package list.

The field at the top filters by package name: only the transactions that changed a matching package stay, and in
each, the matching packages are in bold. **Package → Show in History** opens the window filtered by the selected
package.

## Undoing a transaction

**Mark Changes to Undo** marks the changes that take the packages of the selected transaction back to where they
were:

| The transaction | Marked to undo it |
|---|---|
| installed a package | removal |
| upgraded a package | downgrade to the version before, if a repository still has it |
| downgraded a package | upgrade, if the version before is the newest one |
| removed a package | installation of that version, or of the newest one if that version is gone |
| changed an install reason | the reason back |

Kram does not run anything at this point: the marks are added to the ones you already have, and the package list
switches to *Marked*. Review them, change what you want, and [apply them](applying-changes.md) as any other marks.

Some changes cannot be undone, and Kram lists them with the reason:

- **The version before is gone.** Fedora's repositories keep the newest update of a package and the version the
  release shipped with, so undoing an upgrade often fails, while undoing an installation or a removal almost always
  works.
- **The package changed again since.** A later transaction upgraded or removed it: undoing the older one would undo
  the later change too, so Kram leaves it alone.
- **Several versions are installed**, as with the kernel: remove the one you want with `dnf5 remove`.
- **Another package obsoleted it**: it was replaced by a package of another name.

### A transaction that changed groups or environments

Installing or removing a [group or environment](package-list.md#filters) also records it in dnf's database. Undoing
only the packages would leave it recorded as installed, and removing it afterwards can take packages that were there
before. So for such a transaction the button is **Undo Transaction…**: Kram reverts it as `dnf5 history undo` does,
the packages and the group records together, shows what that does, and runs it when you agree. Nothing is marked, and
your marks stay. It fails as a whole when a version it needs back is no longer in the repositories.

Kram has no rollback of every transaction after a given one (`dnf5 history rollback`); undo and apply them one at a
time, the newest first.
