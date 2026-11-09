# Kram — a Synaptic-style package manager for Fedora

Repository: https://github.com/elmodos/kram · App ID: `io.github.elmodos.Kram`

MVP plan. Goal: give a long-time Debian user on Fedora the same feeling Synaptic gives — the full
package list, full control, and nothing happens until you press "Apply".

## 1. Principles (what we do and what we don't)

- **One dense tool window**: menu, toolbar, filter sidebar, table, detail tabs, status bar. No "store",
  cards, screenshots, ratings or animations.
- **Mark → review → apply.** Clicking a checkbox only *marks* an action. Nothing is installed or removed
  until "Apply" is pressed and the full list of changes, dependencies included, has been shown.
- **Honesty**: the GUI shows what `dnf5` would do and can print the equivalent command
  (`dnf5 install … remove …`), for trust and for copying into a terminal.
- **Speed**: start-up ≤ 2–3 s on a warm cache, search is instant (≤ 50 ms per keystroke).
- **The GUI never runs as root.** Only a small helper does, for the duration of a transaction.
- **English source strings, translated with gettext** (see §9).

## 2. Technology

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.14 (system) | libdnf5 bindings are packaged, nothing to build |
| GUI | **PySide6 (Qt 6)** | native Breeze look on KDE; `QTreeView` + a custom model handles 100k rows virtually; classic widgets (menus, toolbars, splitters) without libadwaita's mobile-first patterns |
| Package backend | **`python3-libdnf5`** (direct bindings) | the same logic as `dnf5`; reading works without root from the system cache |
| Privileges | **pkexec + our own helper** (JSON over stdin/stdout) + polkit policy | full control over progress and errors; one password prompt per session |
| COPR | `dnf5 copr …` through the helper + Copr API (`/api_3/`) for project search | the plugin already generates correct .repo files per chroot |
| Translations | **gettext** (`po/*.po`), Qt's own `qtbase_*.qm` for standard buttons | standard on Linux, supported by Weblate / Fedora's translation platform, works in non-Qt code |
| Tests | pytest, a fake backend; real transactions in a throwaway Fedora container | |
| Quality | ruff | |
| Packaging | RPM spec + our own COPR | installs like everything else |

Alternatives and why not (for now):
- **GTK4 + libadwaita** pushes towards the mobile HIG with no classic menu bar; looks foreign on KDE.
  GTK3 is a dead end.
- **dnf5daemon-server (D-Bus)** is the official route (dnfdragora uses it), but it is not installed by
  default, its API is still moving, it does not cover COPR, and progress/errors are harder to control.
  The transaction side is kept small so it can be swapped for dnf5daemon later.

### Measured on the development machine (Fedora 44, dnf5 5.4.6)
- `load_repos()` without root, `cache_only=True`: **~1.2 s**; a full query: ~1 s.
- **109,171** NEVRAs in the sack, **70,319** unique names, 73,247 "latest x86_64+noarch".
- 3,090 installed. `from_repo_id` of installed packages: `updates`, `fedora`, a hash like `6ecc2dfa…`
  (packages from the Anaconda installation image), `<unknown>` (not recorded), `@commandline` (installed
  from a local .rpm), `copr:…`, third-party repos → origin classification is real and useful (§4).

## 3. Architecture

```
┌──────────────── GUI process (user) ──────────────────────────────┐
│  Qt MainWindow ── PackageTableModel ── filters / SearchIndex      │
│        │                    ▲                                     │
│        ▼                    │ snapshot (list[PkgRow])             │
│  MarkSet (marked actions) ─ │ ── Catalog (worker thread, libdnf5) │
│        │     resolve() for the preview (no root, no downloads)    │
└────────┼──────────────────────────────────────────────────────────┘
         │ pkexec kram_helper.py   (JSON lines over stdin/stdout)
┌────────▼──────── helper (root, lives for the session) ────────────┐
│ refresh | transaction{install,remove,upgrade,downgrade,reinstall, │
│ mark_user,mark_dep} | (M4: copr, repo enable/disable)             │
│ → events: download, rpm step, scriptlet, question, log, done      │
└───────────────────────────────────────────────────────────────────┘
```

Key decisions:
- **libdnf5 lives on one worker thread** (`Base` is not thread-safe). The GUI receives a *flat snapshot*
  of plain dataclasses, no SWIG objects. Details (dependencies, files, changelog) are lazy queries on the
  same thread.
- **One row = `name.arch`**, not a NEVRA. Inside: installed version, best available version, and the list
  of all versions (the "Versions" tab). Other arches (i686) are shown only when installed.
- **The goal is built once, by one function** (`kram.helper.kram_helper.build_goal`): the GUI resolves it
  unprivileged for the preview dialog, the helper resolves and runs the same request.
- **The helper is small and dumb**: it validates JSON requests against a whitelist, accepts no file paths
  or arbitrary arguments. It is the security boundary — review it separately.
- After every transaction or refresh the catalog reloads in the background, keeping cursor and filter.

### Repository layout
```
kram/
  __init__.py      # APP_ID, homepage
  __main__.py      # QApplication setup, translators
  i18n.py          # gettext setup: _(), ngettext(), pgettext(), N_()
  core/            # no Qt; unit-tested
    catalog.py     # libdnf5 → PkgRow snapshot, lazy details, resolve(), provides/file search
    model.py       # PkgRow, Origin, Status, details/preview dataclasses
    origin.py      # origin classification
    filters.py     # sidebar Status / Origin / Groups filters
    search.py      # ranked in-memory search
    marks.py       # MarkSet, allowed actions, equivalent dnf5 command
    evr.py         # RPM version ordering
  ipc/client.py    # pkexec'd helper process, event stream
  helper/kram_helper.py   # the root process (standalone: stdlib + libdnf5 only)
  ui/              # main_window, sidebar, package_model, details, apply_dialog, progress_dialog, icons
po/                # kram.pot + one <lang>.po per translation
data/              # .desktop, AppStream metainfo, polkit policy, icon
packaging/kram.spec
.copr/Makefile     # SRPM for COPR's "make srpm" build method
scripts/           # i18n.sh, container_check.sh, rpm_check.sh, helper_driver.py, m0_helper_check.py
tests/
docs/              # this plan, COPR notes, README screenshots
```
Packaging: `data/io.github.elmodos.Kram.{policy,desktop,metainfo.xml,svg}`, `packaging/kram.spec`,
`.copr/Makefile` (M5).

## 4. Data model and statuses (the "S" column)

Status icon (Synaptic-style box with colour/glyph):

| Status | Meaning |
|---|---|
| ☐ | not installed |
| ■ | installed, up to date |
| ■↑ | installed, an upgrade is available |
| ■↓ | installed version is newer than any repository has (local build, version withdrawn) |
| ■? | installed, no enabled repository provides it ("orphaned") |
| ■· | installed as a dependency and no longer needed (autoremove candidate) |
| marks | + install, ↑ upgrade, ↓ downgrade, R reinstall, ✕ remove, U/D install reason; 🔒 versionlock (later) |

A separate narrow **Origin** column (second column, like the Ubuntu icon in Synaptic):

| Origin | Rule |
|---|---|
| Fedora (official) | `fedora`, `updates`, `updates-testing`, `fedora-cisco-openh264`, the Anaconda installer repo (hash id / `anaconda`) |
| COPR | `repo_id` starts with `copr:` → shown as `owner/project` |
| Third-party | any other repo (rpmfusion, google-chrome, vscode…), with the repo name |
| Local | `@commandline` |
| Unknown | `<unknown>`: dnf did not record where it came from |

For installed packages the origin is where it was installed *from*; for others, where it would come from.
The list of "official" repos should move to a config file (RHEL/CentOS Stream later).

Table columns: S · Origin · Package · Installed version · Latest version · Repository · Size · Summary.
Sortable by any column; widths and order are saved.

## 5. UI (MVP)

Laid out like Synaptic:

- **Menu**: File (Reload, Reload from cache, Quit) · Edit (Mark All Upgrades, Unmark All, Apply, Copy,
  Find) · Package (mark for install/upgrade/reinstall/removal, downgrade to…, install reason, unmark,
  Properties, Back) · Settings (Repositories, COPR) · Help.
- **Toolbar**: Reload · Mark All Upgrades · Apply · Properties · Repositories · search mode + field.
- **Sidebar** with view buttons below it (as in Synaptic):
  - *Status*: All / Installed / Not installed / Upgradable / Installed by user / Unneeded dependencies /
    Orphaned / Newer than repository / Marked.
  - *Origin*: Fedora / COPR (each project) / Third-party (each repo) / Local / Unknown.
  - *Groups*: comps groups and environments (Fedora's equivalent of "Sections"; the RPM `Group` tag is dead).
  - *Search results*: query history.
  - *Custom filters*: user-defined condition lists (2026-11-04).
- **Table**: clicking the status box opens the action menu, as in Synaptic; double click installs/upgrades
  or unmarks. Multi-selection applies an action to all rows it fits. Marked rows are tinted.
- **Detail tabs**: Description · General (NEVRA, repos, license, URL, packager, build date, sizes, install
  reason) · Dependencies (Requires / Recommends / Suggests / Required by / Conflicts / Obsoletes / Provides,
  clickable) · Files · Versions (all installed and available) · Changelog.
- **Status bar**: "N listed, M installed, K upgrades. X to install/upgrade, Y to remove." + metadata age.
- **Apply dialog**: tree of changes (dependencies and unneeded removals listed separately), download size
  and disk space change, the equivalent dnf5 command, "download only". Removing essential packages
  (kernel-core, systemd, dnf5, …) shows a red warning.
- **Progress window**: download and rpm progress, current step, expandable log, "close when finished".

Keyboard: `Ctrl+F` search, `Ctrl+R` reload, `Ctrl+P` apply, `Ctrl+U` mark upgrades, `Ins` install,
`Del` remove, `Ctrl+Z` unmark, `Alt+←` back.

## 6. Search (that works)

The pain with dnfdragora is search through separate backend queries over fixed fields. Here:

- After loading, an **in-memory index** over ~70k `name.arch`: lowercased name, summary, description.
- **Incremental search** while typing (150 ms debounce) within the current sidebar filter.
- Modes: *Name* (default) · *Name + summary* · *Description* · *Provides* (libdnf5 `filter_provides`) ·
  *File* (`filter_file`, e.g. `/usr/bin/foo` or `*/libfoo.so*`).
- Syntax: several words = AND; `^name` / `name$` anchors; `*` / `?` globs.
- **Ranking**: exact name → name prefix → name substring → summary → description; within a tier installed
  first, then shorter names. The first row is "the package you meant".
- Clicking a column header sorts the results instead (Synaptic behaviour); a new query ranks again.

## 7. COPR and repositories (M4)

**Repositories** dialog (Settings → Repositories): every repo from `/etc/yum.repos.d` — enabled checkbox,
id, name, package count, file, priority, enable/disable buttons. debuginfo/source collapsed by default.

**COPR** dialog:
- Enabled projects (from `copr:` repos): owner/project, enabled, package count, how many are installed.
- **Add**: `owner/project` field + "Search" (Copr API `/api_3/project/search`) with results (name,
  description, whether a chroot exists for the running Fedora).
- **Enable / Disable / Remove** → the helper runs `dnf5 copr enable|disable|remove`.
- Before removing: "N packages are installed from this COPR — they will become orphaned; show them?".
- When adding: a one-line note that COPR projects are not reviewed by Fedora.

## 8. Privileged helper and security

- Installed as `/usr/libexec/kram-helper`, started with `pkexec`, polkit action
  `io.github.elmodos.Kram.helper` with `auth_admin_keep`. During development the generic
  `org.freedesktop.policykit.exec` action is used.
- Protocol: JSON lines (documented at the top of `kram_helper.py`). Requests: `ping`, `refresh`,
  `transaction{install,remove,upgrade,reinstall,downgrade,mark_user,mark_dep,upgrade_all,download_only}`,
  `answer`, `quit`. Events: `log`, `resolved`, `download`, `rpm`, `question` (OpenPGP key import: the GUI
  shows the fingerprint and asks), `done{ok,error}`.
- Validation: known ops only, package specs matched by a regex (no `/`), no file paths from the GUI
  (local .rpm files: a separate `local_install` request, §10).
- The helper does not translate: pkexec strips the locale. `log` events carry an English text plus a key
  and parameters, and the GUI shows the translated message.

## 9. Translations

- Source strings are English, marked with `_()`, `ngettext()` (plurals), `pgettext()` (same English word,
  different meaning) and `N_()` (mark only) from `kram.i18n`.
- `po/kram.pot` is the template, `po/<lang>.po` the translations. `scripts/i18n.sh update` re-extracts
  and merges; `scripts/i18n.sh new <lang>` starts a new language; `scripts/i18n.sh check` validates.
- When running from a checkout, `kram.i18n` compiles `po/*.po` into `kram/locale/` (gitignored) on start.
- Tests fail if the template is stale, a catalog is incomplete or has fuzzy entries, or a translation uses
  `{placeholders}` that the source does not have.
- The language follows the environment (`LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG`).

## 10. Milestones

**M0 — spike.** Confirm: libdnf5 on a worker thread + a PySide6 model with 70k rows (smooth scrolling),
`Goal.resolve()` without root, the helper running a transaction through pkexec with streamed progress.

M0 results (2026-11-03):
- ✅ Catalog: 70,561 rows (`name.arch`), 1.7–2.2 s without root on a warm cache. Statuses come from
  libdnf5's `filter_upgradable/extras/unneeded/userinstalled`, no hand-written EVR comparison.
- ✅ Qt: a custom `QAbstractTableModel` over 70k rows, ~17 ms per page scrolled (offscreen); name
  substring filter ~5 ms.
- ✅ libdnf5 on one thread (`ThreadPoolExecutor(max_workers=1)`), results delivered via a Qt signal.
- ✅ `Goal.resolve()` without root (fish → + ncurses-term).
- ✅ Helper: JSON-lines protocol, spec validation, streamed download events.
- ⚠️ SWIG trap: the Python callback object must be kept referenced, otherwise it is garbage collected and
  libdnf5 aborts with `std::terminate`. An exception escaping a callback also kills the process → every
  callback is wrapped in `_guarded`. `add_new_download` must return an `int`.
- ✅ Real run through `pkexec` (uid 0) + `Transaction.test()`: resolve → download → rpm test OK.
  In test mode the rpm callbacks (`install_*`, `script_*`) are not called; in a real transaction
  (container, M3) they are.

**M1 — read-only browser.** Main window, all table columns, statuses and origins, Status/Origin sidebar,
Description/General/Dependencies/Versions tabs, status bar.

M1 (2026-11-03): ✅ menus/toolbar/sidebar (Status; Origin broken down per COPR project and third-party
repo), sorting by any column, detail tabs incl. "required by" and clickable dependencies (jump to the
providing package, Alt+← back), all installed/available versions, changelog, metadata age, window /
columns / filter saved in `~/.config/kram/kram.conf`. Uninstalled `-debuginfo`/`-debugsource` hidden.

**M2 — search.** Index, modes, ranking, search history in the sidebar, benchmark.

M2 (2026-11-03): ✅ ranked search (exact → prefix → substring → summary → description; then installed,
shorter, alphabetical), AND terms, `^`/`$`/`*`/`?`, modes Name / Name + summary / Description
(descriptions load with the catalog, +0.1 s) / Provides / File (libdnf5 on the worker thread, stale
results dropped). Header click sorts results, a new query ranks again, an empty one restores the user's
column sort. Search history in the sidebar (Enter or 1.5 s idle, up to 30, persisted). Version columns
use RPM ordering. Timing: 20–45 ms typical query, ~130 ms for one letter (69k results; 150 ms debounce).
The Provides `*word*` fallback needs ≥ 3 characters (a libdnf5 query cannot be cancelled).

**M3 — transactions.** MarkSet, action menu, Mark All Upgrades, preview with dependencies, helper,
progress, reload afterwards, metadata refresh, install reason, OpenPGP keys.

M3 (2026-11-03): ✅ marks (install / upgrade / reinstall / downgrade to a version / remove / install
reason), status-box action menu, double click, Mark All Upgrades, "Marked" filter, status bar counts.
Apply → unprivileged resolve with the helper's own `build_goal` → changes dialog (groups, dependencies,
sizes, essential-package warning, equivalent command, download only) → helper through pkexec (lives for
the session, one password) → download / rpm / scriptlet progress, log, key import confirmation.
"Reload" refreshes metadata through the helper; "Reload from cache" needs no root.
Verified with real root transactions in a Fedora 44 container: `scripts/container_check.sh` (install with
key import, reason change, reinstall, removal with unneeded dependencies, unsatisfiable request,
download only, refresh).

**i18n (2026-11-03)**: ✅ all strings English + gettext, Ukrainian catalog complete (§9).

**M4 — repositories and COPR.** The dialogs from §7.

M4 (2026-11-03): ✅ Settings → Repositories: every configured repo with an enabled checkbox, package
count, priority, origin and file; debuginfo/source hidden by default; changes are persisted by the helper
with `dnf5 config-manager setopt <id>.enabled=…` (written to `/etc/dnf/repos.override.d/`, the `.repo`
files are untouched) and new repos' metadata is loaded right away. Settings → COPR: enabled projects with
package and installed counts; enable / disable / remove (warns how many installed packages will be
orphaned and can show them) and "show packages"; search through the Copr API ranked by name, marking
whether each project builds for the running Fedora/arch; an exact `owner/project` can be enabled without
searching. The Copr search API is slow (10–20 s per query, whatever the limit), hence a 60 s timeout.
Helper arguments are validated so nothing starting with `-` reaches `dnf5` as an option. Verified in the
container (`scripts/container_check.sh`): repo disable/enable, unknown repo rejected, COPR enable /
setopt on a COPR id / disable / remove, non-existent COPR project fails cleanly.

**M5 — polish and packaging.** comps groups in the sidebar, save/load marks to a file, RPM spec, .desktop,
metainfo, polkit policy, our own COPR, README with screenshots.

M5 (2026-11-03): ✅ Groups view: user-visible comps groups (translated names when the metadata has the
language; installed groups get the installed box; description as a tooltip). File → Save Markings / Read
Markings: plain text, `<action> <name>.<arch> [<version>]` per line; reading adds to the current marks and
reports lines that are invalid or no longer apply. Packaging: `packaging/kram.spec` (pyproject macros;
`%check` runs desktop-file-validate, appstream-util and the test suite), `data/` (desktop file, metainfo,
polkit policy with its own action for `/usr/libexec/kram-helper`, icon), `.copr/Makefile` for COPR's
*make srpm* method. An installed Kram starts `pkexec /usr/libexec/kram-helper` (Kram's own polkit message);
a source checkout still runs its own helper through `pkexec python3`. `scripts/rpm_check.sh` builds the
SRPM and RPM the way COPR does in a container, installs it and checks the layout and the helper.
COPR project: https://copr.fedorainfracloud.org/coprs/elmodos/Kram/ (2026-11-04), installed and upgraded
through Kram itself. README screenshots (`docs/screenshots/`) are real Plasma screenshots.

**Custom filters (2026-11-04)**: ✅ Settings → Custom Filters (or right-click the sidebar): named filters of
conditions on name, name or summary, description, provided capability, status, origin, repository, group, install reason,
architecture and installed size, matching all or any; a live count while editing; "New Filter from Current
View" turns the sidebar selection plus the search into conditions. Stored as JSON in kram.conf
(`filters/custom`), compiled to in-memory predicates (`kram/core/custom_filters.py`).
A Provides condition (exact, "is not", or a glob; added 2026-11-09) needs libdnf5, which lives on its own thread, while
filters run on the GUI thread: the catalog load answers the saved filters' capabilities into `CatalogSnapshot.provides`,
and the editor asks for new ones in the background ("Counting…"). `application()` is what rpm-build gives a package with
a `.desktop` file in `/usr/share/applications`: it means "has a menu entry", so it leaves out terminal programs.

**After the MVP**: versionlock (🔒), offline system upgrades
(`dnf5 offline`), dnf-automatic settings, in-app language override.

**Changelog in the app** (requested 2026-11-07, not designed yet): show what changed in each version somewhere
in Kram. Source: commits that change something a user can notice end with `Changelog: <Area>: <change>` git
trailers (from c4ed714 on), read with `git log vA..vB --format='%(trailers:key=Changelog,valueonly)'`; the
release step will collect them into a file shipped with the package (and the metainfo `<release>` notes).

**Cache** (after the MVP, planned 2026-11-07, designed 2026-11-09): Settings → "Package Cache…", a small dialog
with one row per cache in a framed list, cells separated by lines as in Discover: icon, name, one-line description,
size, file count where it means something, and its own button. Not on the toolbar. It opens wide enough for one
line per description and can shrink: the text wraps, and the list scrolls when the window is too low.
- **Sizes need no password**: every cache is readable by a normal user (except PackageKit's `tmpdir.*`
  directories, which are left out of the count). They are counted on a background thread and again after each
  clean. A row whose directory does not exist is hidden; an empty cache disables its button.
- **DNF: downloaded packages** (`/var/cache/libdnf5/*/packages`): `dnf5 clean packages` through the helper. With
  `keepcache=False` (the default) packages go away after a successful transaction; what is here comes from
  interrupted transactions and "download only".
- **DNF: repository metadata** (the rest of `/var/cache/libdnf5`): one action, "Download Again…", with a
  confirmation (traffic, needs the internet): `dnf5 clean metadata dbcache`, then the normal refresh, then a
  catalog reload. It cannot be a plain clean: the catalog reads only this cache (`cacheonly="all"`), so without
  metadata every available package disappears. Marks survive the reload; if the download fails (no network),
  marks on packages that are no longer available are dropped and the usual "N repositories have no metadata"
  warning shows. For a damaged cache and leftovers of removed repositories; normal updating stays in "Reload".
- **DNF cache of your user** (`~/.cache/libdnf5`): `dnf5 clean all` without the helper. Only `dnf` run as the user
  writes here; Kram itself reads the system cache.
- **Discover / GNOME Software** (`/var/cache/PackageKit`): rpms they download for offline updates and do not clean
  up (3.5 GB, 467 rpms on the author's laptop, 2026-11-07). Removes only `*/metadata/*/packages/*.rpm` (3.3 of those
  3.5 GB): the metadata stays intact for a running daemon and Discover. Regular files only, no symlinks followed.
  Disabled with an explanation while an offline update or upgrade is prepared (`/system-update`,
  `/var/lib/PackageKit/prepared-update`, `/var/lib/PackageKit/prepared-upgrade`) or PackageKit runs a transaction.
- **Helper**: `{"op": "clean_cache", "target": "dnf_packages"|"dnf_metadata"|"packagekit"}`. No paths from the GUI.
  It checks `lock_holder()` first (stage "locked") and repeats the PackageKit checks itself.
- **Buttons per row, not checkboxes and one Clean**: the actions differ (root or not, one downloads again).
  Only the metadata action asks for confirmation: the rest is harmless and `pkexec` already asks for the password.
- **As built (2026-11-09)**: an active PackageKit transaction is found with `GetTransactionList` over D-Bus, asked
  only if the name already has an owner, so the check does not start the daemon (with a real daemon in a container:
  `ao 0` when idle, refused during `pkcon refresh force`). `dnf5 clean packages` and `clean metadata dbcache` also
  empty the directories of repositories that no longer exist. `scripts/container_check.sh` covers the helper's three
  targets and cleaning a user's cache. Each row also shows where its files are: a link that opens the folder in the
  file manager (`*/packages` for the packages, spread over a folder per repository, opens the cache's top folder;
  PackageKit's path names its release folder when there is only one).
- **Rules for dialogs that came out of this** (`tests/test_main_window.py`): an action that needs the catalog is
  disabled until it has loaded, not silently ignored; a progress dialog is a child of the dialog that started it, so
  the window manager keeps it on top; the line above the bars stops saying "Waiting for authentication" as soon as
  the helper reports work.

No per-version pruning ("remove already upgraded packages"): with `keepcache=False` dnf keeps none, and for
PackageKit cleaning all its rpms is simpler.

**New Fedora release** (designed 2026-11-09): Kram tells that a new major release exists and audits what moving to it
would do. It never offers the upgrade itself: that is too much responsibility.
- **Setting**: Settings → "Watch Fedora Releases", a checkbox, on by default. Its tooltip says Kram asks Bodhi.
- **Source of truth**: Bodhi, `https://bodhi.fedoraproject.org/releases/?rows_per_page=100&exclude_archived=true` (under
  a second, 12 kB). Keep `id_prefix == "FEDORA"`, `state == "current"` and a numeric `version`: 43, 44 and 45 on
  2026-11-09, while F46 is `pending`. `eol` gives the end of support. `fedoraproject.org/releases.json` mixes in "45 Beta".
- **When**: only on Reload, not on "Reload from cache" and not at start. From the GUI process with
  `QNetworkAccessManager`, as the Copr search does; no helper. A failed request is silent and the last result stays.
- **Which systems**: `/etc/os-release` with `ID=fedora` and a numeric `VERSION_ID`; nothing on Rawhide, ELN or derivatives.
- **Target**: the newest current release above the running one, at most +2, the longest jump Fedora supports.
- **Toolbar button**: after COPR, hidden unless there is a target, text "Fedora 45", tooltip "Fedora 45 is available, you
  have 44". Icon `fedora-logo-icon` (fedora-logos), falling back to `system-upgrade`. The result is kept between runs in
  the settings and goes away when the system reaches that release or the setting is turned off.
- **Dialog**: the end of support of the running release, then the audit. Kram has no upgrade action of its own and no
  command to copy: links to the official upgrade guide and release notes, and a button that hands over to the program
  that can upgrade, opened on its updates page: "Open Discover" (`plasma-discover --mode Update`) or "Open GNOME Software"
  (`gnome-software --mode=updates`). If both are installed, the one matching `XDG_CURRENT_DESKTOP`; if neither, no button.
- **Audit, COPR part**: runs when the dialog opens. For each enabled COPR project, whether it has a `fedora-45-<arch>`
  chroot, with its installed package count (`/api_3/project`, 4 projects in 4.3 s).
- **Audit, simulation**: starts with a "Check" button, because it downloads metadata (82 MB and 68 s on the author's
  laptop; resolving takes 2 s). A separate libdnf5 Base on the dnf thread with `releasever` set to the target and its
  own cache directory, unprivileged, `Goal.add_rpm_distro_sync()`, resolved and never run: first without
  `allow_erasing`, whose problems are the blockers, then with it for what the upgrade would do. It shows blockers, what
  is removed (without the rotation of old kernels), installed packages nothing in the target provides, downgrades,
  enabled repositories without packages for the target, and the download size against free disk space.
  The result stays in memory for the session; the metadata is deleted when the dialog closes.
- **Prototype on the author's laptop** (Fedora 44 → 45): all 16 repositories and 4 COPR projects have builds, yet the
  upgrade does not resolve without erasing: `VirtualBox-7.2` needs `libvpx.so.9`. With erasing: 2993 upgrades, 50 installs,
  20 downgrades, 5366 MB, and 18 installed packages have nothing in 45. So the COPR check alone would have said "fine".
- **As built (2026-11-09)**: `kram/core/distro.py` (Bodhi, the target, the upgrade program), `kram/core/upgrade_audit.py`
  (the simulation; it deletes its metadata as soon as it has the answer, not when the dialog closes, so closing the dialog
  during a check leaves nothing behind), `kram/ui/upgrade_dialog.py` (kept for the session, so a finished check stays).
  A check holds the dnf thread for as long as its download takes, so the dialog cannot be closed meanwhile (it is modal:
  the rest of Kram waits with it, and nothing looks broken for no visible reason). Cancel stops the transfers through
  libdnf5's download callbacks and deletes the metadata, in 3 s against a server that accepts and then says nothing; the
  last seconds, reading and resolving, cannot be interrupted. A log under the results follows it, as in the progress
  dialog: each repository started and finished, mirror failures and the steps of the resolve.

**Local .rpm installer** (designed 2026-11-07, target 0.2.0; was postponed for security reasons on 2026-11-05).
A gdebi-style dialog for one package file.
- **Opening it**: File → "Open Package File…" and dropping an `.rpm` on the main window (window-modal over it);
  `kram /path/file.rpm` shows only the dialog, no main window. The existing .desktop file gets `Exec=kram %f`
  and `MimeType=application/x-rpm;`, so file managers offer "Open with Kram" and the menu keeps one entry.
  The dialog is a self-contained component (catalog, dnf thread, helper client), the parent window is optional.
  It shows a busy state while the catalog loads.
- **One file only.** A vendor who ships an app as several rpms should publish a repository.
- **Marks in the main window are left alone**: the transaction holds only this package and what it pulls in; a
  line says "N marks in the main window are not part of this and stay". While any modal dialog is open or a
  transaction runs, the main window ignores dropped files and disables the menu action (an explicit check, not
  only Qt modality). A second Kram process started from a file manager meets the rpm lock and gets a plain
  "another package operation is running" error.
- **Header**: name, full version and arch, summary, a coloured state line, signature (signed by the Fedora key /
  a repo's key, unknown key, unsigned; the last two are a warning, since dnf5 does not check local packages by
  default), hints: "also available from repository X (version Y)", "gets no updates unless it adds a repo".
- **States and the main button**: not installed → Install ("N more packages, download X MB, takes Y MB");
  older installed → Upgrade (1.2 → 1.3); newer installed → Downgrade (with a warning); the same version →
  Reinstall (the main window can only reinstall a version a repo still has) plus the `rpm -V` result ("3 files
  missing or changed"; unreadable files listed apart as "could not check"; the buttons are disabled and the
  status bar says what runs while it checks); not installable → only Close, with the solver's reason or the
  wrong arch. No "Remove" here: removing installed packages belongs to the main window.
- **Tabs**: Description, Details (license, URL, vendor, packager, build date, sizes), Dependencies (requires,
  plus what the resolved transaction actually brings), Files, Changelog, **Scripts** (`%pre`/`%post`/triggers:
  code that runs as root; the header says so when there are any). Read from the file's header with python3-rpm.
- **No separate confirmation**: the dialog already lists the changes; the button goes to pkexec and the normal
  progress dialog.
- **Helper**: a new request `{"op": "local_install", "path": ..., "sha256": ..., "exclude_weak": [...], "action":
  "install"|"reinstall"|"downgrade"}`. The helper opens the file with the caller's rights (`setgroups`,
  `setegid`, `seteuid` to `PKEXEC_UID`; `O_NOFOLLOW`; a regular file ending in `.rpm`; a size limit), clones it
  into its own 0700 directory (reflink via `FICLONE`, instant on btrfs and XFS, a plain copy otherwise, after
  checking free space), hashes the copy while copying and refuses if it differs from what the dialog showed,
  then resolves with `add_cmdline_packages` on the copy and removes it afterwards. So root never reads a file
  the user cannot (checked in a container: another user's file, a symlink, a FIFO and a root-group file are all
  refused), and exactly the reviewed file is installed. Signature state comes from `rpmkeys -Kv` (an OpenPGP
  line with OK / NOKEY, or none for an unsigned package).

**Choosing recommended packages** (done 2026-11-07): one shared widget for the installer and the normal apply
dialog. A checkbox per *recommendation* (a `Recommends:` of a package in the transaction), not per package: a
recommendation can be a choice like `(libvirt-daemon-kvm or libvirt-daemon-qemu)`. Unchecking one puts every
package that provides it into libdnf5's `exclude_from_weak` (`dnf5 --setopt=exclude_from_weak=a,b`): those are not
installed as weak dependencies, but still as hard ones ("still installed: something else requires it"), and the
solver does not swap in the other alternative. User excludes were tried first and did exactly that swap
(virt-manager: 1.1 GB → 2.4 GB with every qemu arch). The rest still installs with the "weak dependency" reason,
so autoremove stays correct. The marked packages' own recommendations come first; those of dependencies go in a
collapsed group, packages pulled in by their own `Supplements:` get a row each. Every toggle resolves again on
the dnf thread (~0.4 s); the first preview also resolves once without each direct recommendation (up to 10) to show
what it adds with everything it pulls in. The catalog's long-lived base restores `exclude_from_weak` after each
resolve. Requests carry `"exclude_weak": [names]` (validated like other specs); the equivalent command shows the
`--setopt`. Initial state: what the solver picked with `install_weak_deps`.

**Order**: recommended-packages widget in the apply dialog (done) → helper `local_install` with container tests
(done) → installer dialog inside the main window (done, translated along the way: the tests require complete
catalogs) → the dialog-only mode and .desktop (done 2026-11-08: `kram file.rpm` loads the catalog in the dialog;
the helper refuses with stage "locked" while another process holds rpm's transaction lock, found with F_GETLK,
because rpm itself then reports "Signature verification failed"); the cache dialog later. README and metainfo with the release.

As built (2026-11-08), beyond the design above: the Dependencies tab marks each requirement as installed (by which
package), provided by the file itself, coming with this transaction, not installed, or unavailable; a kernel-like
(installonly) file is "installed next to" the old version, not an upgrade; a newer version in a repository is a
warning ("the next system update will install it over this one"); the progress log calls rpm's erase of a
replaced copy "cleaning up the old copy" and counts packages, not rpm steps. Checked in a container with built test
packages: install, upgrade, downgrade, reinstall, installonly, unsatisfiable, foreign arch, newer in a repo
(`scripts/check_local_versions.py`).

**Reasonable, but not planned unless users ask for it** (2026-11-06): moving transactions from our helper to
dnf5daemon, or supporting both. For: no root code of our own, standard dnf polkit actions, local .rpm and
offline upgrades come almost for free. Against: dnf5daemon 5.4 has no `mark` (install reason) and cannot add
repositories (COPR), so the helper would stay anyway; `auth_admin_keep` asks again every few minutes instead of
once per session; `dnf5daemon-server` is not installed by default; the `v0` API changes between dnf5
versions; D-Bus with complex types is awkward from PySide6; harder to test in containers. Both at once only
makes sense as a migration path.

**Decided against** (2026-11-04): transaction history with undo/rollback (`dnf5 history`). Not planned; `dnf5
history` covers it from the terminal.

## 11. Risks

| Risk | Mitigation |
|---|---|
| libdnf5 SWIG bindings are fragile (segfaults, leaks, objects outliving `Base`) | all of libdnf5 on one thread; the GUI only holds copies; callbacks kept referenced and guarded |
| Stale metadata cache (the GUI reads the system cache without root) | metadata age in the status bar; "Reload" refreshes through the helper |
| GUI and helper resolving differently (repos changed in between) | one shared goal builder; the helper resolves again and shows its own result in the log |
| Changelog/filelists are not downloaded by dnf5 by default | tabs say so; a setting could enable `optional_metadata_types` |
| Modularity / protected packages / dnf5 limits | resolver errors are shown verbatim, no "simplification" |
| 100k rows in Qt | a custom `QAbstractTableModel` over an index list, no `QStandardItemModel` |

## 12. Open questions

1. ~~Project name~~ — **Kram** (Ukrainian *крам*: goods, one's household stuff). Repository
   https://github.com/elmodos/kram, app ID `io.github.elmodos.Kram` (`kram/__init__.py`).
2. KDE-specific integration (KNotification about updates in the tray) — outside the MVP?
3. Should debuginfo/source packages be shown at all (default: no).
