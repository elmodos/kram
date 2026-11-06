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
  (local .rpm files later, separately).
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
conditions on name, name or summary, description, status, origin, repository, group, install reason,
architecture and installed size, matching all or any; a live count while editing; "New Filter from Current
View" turns the sidebar selection plus the search into conditions. Stored as JSON in kram.conf
(`filters/custom`), compiled to in-memory predicates (`kram/core/custom_filters.py`).

**After the MVP**: versionlock (🔒), offline system upgrades
(`dnf5 offline`), dnf-automatic settings, in-app language override.

**Postponed for security reasons** (2026-11-05): installing local .rpm files. Scope: File → "Install Package
File…", drag and drop, `MimeType=application/x-rpm` in the .desktop file; the file shows up in the list marked
for installation (origin "Local (@commandline)") and goes through the normal apply dialog. Why postponed:
- the helper is the security boundary and deliberately takes no paths (`SPEC_RE` forbids `/`); this needs a
  new, strictly validated request type (absolute path to a regular `*.rpm` file, opened by the root helper);
- local packages are usually not signature-checked (`localpkg_gpgcheck` is off by default in dnf5), so the
  apply dialog must warn that the package is unverified and gets no updates unless it adds its own repo;
- the GUI's preview has to load the same file (`add_cmdline_packages`) so both sides resolve the same goal.
Until then: `sudo dnf install ./file.rpm` or Discover.

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
