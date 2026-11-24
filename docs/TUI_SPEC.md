# `kram-tui` — specification

Status: **draft for review** (2026-11-24), branch `feature/tui`. This is what the terminal front end must do and
look like. The reasons behind the decisions, the alternatives that were dropped and the spike measurements are in
`docs/TUI_FRONTEND.md` (decisions T1–T20). The spikes `scripts/spikes/t1_tui.py` and `scripts/spikes/t2_dialogs.py`
show most of it working over the real catalog; where the spec and a spike differ, the spec wins.

Words: **must** is required for the first release; **should** is wanted, and may come later if it says so; **may** is
optional. "The GUIs" means `kram-qt` and `kram-gtk`. Feature names (`DIALOG_APPLY`, …) are those of
`kram/app/parity.py`; §16 gives each one its terminal behaviour.

---

## 1. Scope

1.1 `kram-tui` is a third front end of Kram for text terminals, over the same toolkit-free layer as the GUIs
(`kram/core`, `kram/app`, `kram/ipc`, `kram/helper`). It has **feature parity** with the GUIs: every feature of
`kram/app/parity.py` is SUPPORTED, PARTIAL with a note, or NOT_INTENDED with a reason (§16).

1.2 It must work over SSH and on the Linux console, with no desktop session, as well as in a terminal emulator on a
desktop.

1.3 Non-goals: a mouse-first design (the mouse works where it costs nothing, §6.9); features the GUIs do not have,
except where a terminal needs them (§6.6 search keys, §5.3 small-terminal screen, §9.4 colours).

## 2. Platform and dependencies

2.1 Fedora 43 and later. Python as Fedora ships it. **Textual ≥ 4.0.0** (Fedora 43/44 ship 4.0.0, Fedora 45 ships
8.1.x); every release is tested on both (§14). No Textual API newer than 4.0 may be used without a fallback.

2.2 Package `kram-tui`: `Requires: kram-common = %{version}-%{release}, python3-textual >= 4.0`. Command
`/usr/bin/kram-tui`. It does not conflict with `kram-qt` or `kram-gtk` and is not an `alternatives` choice for
`/usr/bin/kram`: both may be installed (§15).

2.3 The terminal: any that speaks xterm sequences, 16 colours at least, UTF-8 or not (§9.6). Tested on §14.4's
list.

## 3. Architecture

3.1 Code in `kram/tui/`, built like `kram/gtk/`: widgets only; everything else comes from `kram/app` (presenters,
view protocols, actions and menus as data, settings registry, columns, details documents) and `kram/core`. New logic
that both GUIs would need goes to `kram/app`, not to `kram/tui`.

| Module | Holds | Over |
|---|---|---|
| `kram/tui/__main__.py` | entry point, arguments, single run | `kram/__main__.py` (§15.2) |
| `kram/tui/app.py` | `KramApp(App)`: screens, key scopes (§6), colours (§9), layout switch (§5) | |
| `kram/tui/loop.py` | `post(fn)` over the app's asyncio loop (`call_soon_threadsafe` → `call_later`: in order, never waiting — `call_from_thread` waits for fn, which a worker must not), `TuiScheduler` on Textual timers | `kram/core/mainloop.py`, `kram/gtk/loop.py` |
| `kram/tui/palette.py` | `Palette` widget, roles, schemes (§9) | |
| `kram/tui/widgets.py` | `Button`, `CheckBox`, `ChoiceList`, `hint()` (§8) | |
| `kram/tui/package_list.py` | the virtual list (§7.3) | `kram/app/package_list.py`, `columns.py` |
| `kram/tui/sidebar.py` | views and entries (§7.2) | `kram/app/sidebar.py` |
| `kram/tui/details.py` | tab strip and documents (§7.4) | `kram/app/details.py`, `doc.py` |
| `kram/tui/search.py` | search popup (§7.6) | `kram/core/search.py`, `kram/app/search.py` |
| `kram/tui/menu.py` | menu popup, context menus (§7.7) | `kram/app/actions.py` |
| `kram/tui/dialogs/*.py` | one module per dialog (§10) | the presenters named in §10 |
| `kram/tui/root.py` | getting the helper as root (§11) | `kram/ipc/client.py` |

3.2 Long work (catalog load, resolve, details, network) runs on the existing workers (`kram/core/worker.py`);
results reach Textual's thread through `Post` (§3.1). The UI thread never waits on I/O.

3.3 The package list never uses Textual's `DataTable` (T4): it is a `ScrollView` whose `render_line` draws only the
lines on screen from `PackageList`. Small tables in dialogs (repositories, COPR, mirrors, history) may use
`DataTable`.

## 4. Visual language

4.1 **Borders.** Box drawing, square corners: a panel has a single line (`┌─┐│└┘`, Textual `solid`), a modal window
a double line (`╔═╗║╚╝`, Textual `double`). No rounded corners (`round`), no half blocks (`tall`, `wide`), no
shadows. The title sits in the top border on the left, the key hints (§4.5) in the bottom border on the right.

4.2 **Focus.** The panel that has the focus has its border, title and hints in the accent colour; the others are
faint (§9.2). Inside a list the cursor row is reversed when its list has the focus, underlined (16 colours) or in
the blurred cursor colour (high colour) when it has not.

4.3 **Controls.**

| Control | Looks like | Notes |
|---|---|---|
| Button | `< Apply >` one line | focused: reverse; default button: bold; dangerous: error colour; disabled: dim, skipped by `Tab`. Never Textual's three-line `Button` (T14). |
| Checkbox | `[x] Label` / `[ ] Label` | one look everywhere: dialogs, the menu, the repositories table. Never Textual's `Checkbox`/`SelectionList` look. |
| Choice in a strip | ` Name + summary ` reversed among muted ones | search modes, detail tabs; compact form `← Name + summary → 2/5` when they do not fit. |
| Text field | one line, no border, the panel's background | placeholder muted. |
| Progress bar | as wide as its dialog, percentage at the right | indeterminate while the size is unknown. |
| Separator | `─` lines in the rule colour, `│` between tabs | |

4.4 **Glyphs.** Arrows are the classic ones: `← → ↑ ↓` (T10); never `◂ ▸ ▾ ▴`. Ellipsis `…` cuts text. The status
column uses the glyphs of §7.3.4 when the terminal speaks UTF-8, and letters when it does not (§9.6); a setting
chooses letters on a UTF-8 terminal too (§13).

4.5 **Key hints.** Lower case, as the key is typed; the key in the key role (bold), then one word: `[ prev  ] next
v all`. Keys are named as Textual names them on screen: `enter`, `esc`, `tab`, `space`, `ctrl+a`, `f5`, `← →`.
A hint names only keys that work in that panel or dialog now.

4.6 **Text.** Sentence case for every label and title. No exclamation marks. The same words as the GUIs (they come
from the same `_()` strings where they exist).

## 5. Screen layout

5.1 Lines, top to bottom: the **top line** (1 line), the **body** (the rest), the **footer** (1 line).

5.2 Width classes (T5); the switch happens at once on resize, keeping the focus:

| Terminal | Sidebar | Details |
|---|---|---|
| ≥ 100 columns | pinned left, 28 columns (setting, §13) | pinned under the list, 12 lines (setting) |
| ≥ 100 columns and ≥ 34 lines | also lists every view at its bottom | |
| < 100 columns | slide-over on the left, 30 columns, at most 85% | slide-over at the bottom, 11 lines, at most 3/5 of the body |

5.3 Under 40 columns or 12 lines Kram shows only "Make the terminal larger: Kram needs 40×12" centred, and the
quit key. Nothing else reacts. It comes back as it was when the terminal grows.

5.4 **Top line**: `Kram`, the shown filter or search and its row count, the number of marks; on the right, the
catalog's age (`catalog 3 h old`), the warning of `WINDOW_STATUS_BAR` when the catalog is stale (`! 9 days old: f5
reload`), `Fedora N is out: r` when `RELEASE_BUTTON` applies, and a `ROOT` badge when Kram runs as root (§11.2).
What does not fit is dropped from the right, the ROOT badge last.

5.5 **Footer**: Textual's `Footer`, the keys of the focused widget and its parents, the window's keys last. Keys
that do not apply now are left out (§6.3).

## 6. Focus and keys

6.1 **Screens.** The window is one screen. Every popup and dialog is a modal screen over it; the window gets no
keys and no clicks while one is up. Dialogs may stack (Mirrors over Repositories, What's New over About).

6.2 **First responder.** A key goes to the focused widget, then to its parents, its screen and the app; the first
binding that matches wins, priority bindings first. A text field takes printable keys before any binding.

6.3 **Window keys.** The keys of `WINDOW_ACTIONS` belong to the window: they work only while no modal screen is up
and no text field has the focus (`App.check_action` returns False, which also hides them in the footer). One rule,
in one place (T13).

6.4 **Panels.** `g` and `d` show the sidebar and the details and focus them; pressed again while they have the
focus, they hide them and focus the list (T6). `Esc` in a panel focuses the list (a slide-over closes, a pinned
panel stays). Focus moving to the list in any way closes a slide-over. Only one slide-over at a time. `Tab` and
`Shift+Tab` cycle the focus through the shown panels.

6.5 **Keymap.** `scope` is where a key works; actions come from `kram/app/actions.py` by id.

| Key | Scope | Does | Action / feature |
|---|---|---|---|
| `g` / `d` | window | sidebar / details (§6.4) | |
| `/`, `ctrl+f` | window | search (§7.6) | `find` |
| `m`, `f9` | window | menu (§7.7) | `MENU_BAR` |
| `f5`, `ctrl+r` | window | reload | `reload` |
| `R` | window | reload from cache | `reload_cache` |
| `a`, `ctrl+p` | window | apply | `apply` |
| `U`, `ctrl+u` | window | mark all upgrades | `mark_upgrades` |
| `Z` | window | unmark all | `unmark_all` |
| `ctrl+h` | window | transaction history | `history` |
| `ctrl+s` / `ctrl+o` | window | save / read markings | `save_marks`, `read_marks` |
| `?`, `f1` | window | the keys of this screen (§10.20) | |
| `q`, `ctrl+q` | window | quit (§10.19) | `quit` |
| `Esc` | window | focus the list | |
| `↑ ↓ k j`, `PgUp PgDn`, `Home End` | list | move | |
| `← → h l` | list | scroll sideways | |
| `space` | list | the likely mark (as a click on the status cell) | `LIST_STATUS_CLICK` |
| `+`, `Ins` | list | mark for installation / upgrade | `mark.install`, `mark.upgrade` |
| `-`, `Del` | list | mark for removal | `mark.remove` |
| `z`, `ctrl+z` | list | unmark | `unmark` |
| `=` | list | lock / unlock the version | `lock`, `unlock` |
| `Shift+↑ ↓`, `Shift+PgUp PgDn` | list | extend the selection | `LIST_MULTI_SELECT` |
| `.`, `Menu`, `Shift+F10` | list, sidebar | the row's context menu | `LIST_CONTEXT_MENU`, `MENU_SIDEBAR` |
| `s` / `S` | list | sort by… (a choice list) / reverse the sort | `LIST_SORT` |
| `y` / `Y` | list | copy name / name-version-release.arch (§12.3) | `copy_name`, `copy_nevra` |
| `Enter` | list | focus the details | |
| `alt+←` | window | back to the previous filter | `back` |
| `r` | window, while `Fedora N is out` shows | the Fedora N dialog (§10.12) | `RELEASE_BUTTON` |
| `<` `>` | sidebar, details (pinned) | narrower / wider sidebar, lower / higher details; saved | `WINDOW_PANES_SAVED` |
| `[ ]`, `v` | sidebar | previous / next view, list of views | `SIDEBAR_VIEWS` |
| `← →` | sidebar | fold / unfold (Environments) | `SIDEBAR_ENVIRONMENTS_TREE` |
| `Enter` | sidebar | filter the list by the entry | |
| `+ -` | sidebar, on a group | install / remove the group | `SIDEBAR_GROUP_CHANGE` |
| `e` | sidebar, on a custom filter | edit it | `SIDEBAR_CUSTOM_FILTER_EDIT` |
| `[ ]`, `1`–`7`, `t` | details | previous / next tab, a tab, list of tabs | `DETAILS_TABS` |
| `Tab`, `Enter` | details | next link, follow it | `DETAILS_LINKS` |
| `Esc` | any modal | close / cancel (not a running transaction: §10.2) | |
| `Tab` / `Shift+Tab` | any modal | next / previous field or button | |
| `Enter` | any modal | press the focused button | |
| `ctrl`+letter | a dialog | its main action, from a text field too (priority binding) | e.g. `ctrl+a` apply |

6.6 Terminals cannot tell some keys apart (`ctrl+shift+z` from `ctrl+z`, `ctrl+h` from Backspace on some, `Ins`
missing on laptops, `F10`/`F11` taken by the emulator). Every action must also be in the menu, and every key of the
GUIs that a terminal cannot send has a letter in §6.5. The Menu key arrives as `f16` and `Shift+F10` as `f22` in
xterm's encoding: bind both names. The menu shows the TUI's keys, not the GUIs'
(`MENU_ACCELERATORS`).

6.7 A key never acts on something not in sight: no list key works while the list is covered by a slide-over that
has the focus.

6.8 Key names in hints and the footer follow §4.5. `?` lists the keys of the focused scope and the window's.

6.9 **Mouse** (should): a click focuses a panel, picks a row, an entry, a tab, a button; the wheel scrolls; a click
on the status cell does what `space` does; a right click opens the context menu. Nothing needs the mouse.

## 7. The window

### 7.1 Data

7.1.1 The catalog loads on start (`Catalog.load` on the worker), with "Loading the package catalog…" centred in the
list until it is there. A held dnf lock shows "Another package manager is running: waiting" with `Esc` to quit
(the `on_wait` of `Catalog.load`).

### 7.2 Sidebar (`SIDEBAR_*`)

7.2.1 Views: Status, Origin, Groups, Environments, Search results, Custom filters (`kram/app/sidebar.py` `VIEWS`).
The view's name is the panel's title. `[` `]` step through views, `v` lists them. A wide and tall terminal lists
them at the bottom with `●` at the current one; the list is not clickable-only: it follows `[ ]`.

7.2.2 Entries come from `SidebarModel`; each on one line: label (indented by level), the count right-aligned and
muted (`SIDEBAR_COUNTS`). Labels are cut with `…`; counts never are. Bold: an "All" entry and installed groups;
italic: optional groups of an environment.

7.2.3 Changing the view does not filter; `Enter` on an entry does. In a slide-over, `Enter` also closes it.
`SidebarModel.browse(view)` shows a view without filtering, and `filter_view` is the view of the entry the list is
filtered by (the GUIs filter on a view change, so for them the two are the same).

7.2.4 Environments fold: `←` folds, `→` unfolds, `+`/`-` before a parent, on every terminal: no triangles (§4.4)
(`SIDEBAR_ENVIRONMENTS_TREE`).

7.2.5 Empty views say how to fill them, muted and italic: "No searches yet. Press / to search." / "No custom
filters. New Filter from Current View is in the menu."

7.2.6 Context menu (`.`): the entry's actions (`MENU_SIDEBAR`); for a custom filter only the actions that make sense
(`SIDEBAR_CUSTOM_FILTER_MENU`); for a group Install Group / Remove Group (`SIDEBAR_GROUP_CHANGE`).

### 7.3 Package list (`LIST_*`)

7.3.1 Line 0 is the header (bold, muted); lines below are rows of `PackageList` positions. Cells come from
`kram.app.columns.cell_text`; styles from `cell_style` (bold upgradable version, italic held-back and optional,
dim blocked).

7.3.2 Columns, by default: `S` (2 cells: status glyph and flag), Package, Installed, Latest, Repository, Size,
Summary. Hideable and orderable as `HIDEABLE` says (Reason, Update type, Download size are hidden by default), in a
Columns… dialog (§10.18). Widths: Package fits 95% of the shown names (12–48); versions 16; repository 12; sizes 9;
Summary takes the room left, at least 20 (T20). Headers are the short ones (`Installed`, `Latest`, `Size`).

7.3.3 When the columns do not fit, the list scrolls sideways (`← →`); `S` and Package stay in place if they take at
most half the width. A horizontal scrollbar shows only then.

7.3.4 Status glyphs (first cell) and flags (second cell). The Glyph column on a UTF-8 terminal, the Letter column
on one that is not (`LANG=C`, the Linux console without a Unicode font) or when the setting asks for letters:

| State | Glyph | Letter (setting) | Colour role |
|---|---|---|---|
| installed | `■` | `i` | installed |
| not installed | `□` | `p` | muted |
| upgradable | `▲` | `u` | upgradable |
| newer than repository | `▼` | `n` | info |
| orphaned | `◆` | `o` | danger |
| unneeded | `◇` | `a` | muted |
| marked: install | `+` | `+` | marked |
| marked: upgrade | `↑` | `^` | marked |
| marked: remove | `-` | `-` | danger |
| marked: reinstall | `~` | `~` | marked |
| marked: downgrade | `↓` | `v` | marked |
| marked: reason change | `*` | `*` | marked |
| flag: locked (`LIST_LOCK_PADLOCK`) | `L` | `L` | upgradable |
| flag: upgrade blocked | `!` | `!` | danger |
| flag: security advisory | `s` | `s` | danger |

No state is shown by colour alone: the glyph always carries it (§9.5).

7.3.5 Marked rows are tinted in their mark's colour in high-colour schemes (`LIST_ROW_TINT`); in 16 colours the
glyph and the name take the mark's colour instead of a background.

7.3.6 The cursor follows §4.2. Centre scrolling (T11) is on by default (setting). A selection of several rows
(`LIST_MULTI_SELECT`) shows a `▌` in the margin of each selected row; every action of §6.5 and of the menus applies
to all of them; `Esc` clears it.

7.3.7 Sorting (`LIST_SORT`): `s` lists the columns, `S` reverses. The header shows `↑`/`↓` after the sorted column.
A search keeps its ranked order until a sort is chosen (as `PackageList` does).

7.3.8 Empty list (`LIST_EMPTY_EXPLANATION`): the text of `kram/app/empty_list.py` centred in the list, its links as
key hints (e.g. "No package matches “vim” in Installed. a: all packages").

7.3.9 The cursor never ends under a slide-over (§5.2): the list gets extra lines at its end while one is open.

### 7.4 Details (`DETAILS_*`)

7.4.1 Tabs: Description, General, Advisories (only when the package has advisories), Dependencies, Files,
Versions, Changelog (`TABS`). All of them when they fit: `1 Description │ 2 General │ …`, the current one reversed,
Advisories in the upgradable colour; else `← Description → 1/7  ! advisories`. `TabChoice` keeps the chosen tab
across packages and sessions (`DETAILS_REMEMBER_TAB`).

7.4.2 The tab's document comes from `kram/app/details.py` / `doc.py` and is drawn as text: headings bold,
labels muted, links (§7.4.5) underlined in the info colour. It loads when the cursor rests (`DETAILS_DELAY_MS`);
meanwhile the old document stays, dimmed.

7.4.3 Files tab: a tree with every folder open (`DETAILS_FILES_TREE`), or a flat list (`DETAILS_FILES_LIST`, `f`
switches); a filter line at the top (`/` in the tab), matches bold (`DETAILS_FILES_FILTER`); `y` copies the
selected paths (§12.3, `DETAILS_FILES_COPY_PATH`); `o` shows the file in the file manager when there is a desktop
(§12.2, `DETAILS_FILES_SHOW_IN_FM`).

7.4.4 Versions tab: a small table (version, repository, state), the installed one bold.

7.4.5 Links (`DETAILS_LINKS`): `Tab` moves between the links of the document, `Enter` follows. A package or a
dependency selects it in the list (`alt+←` goes back). A web address opens in the browser when there is a desktop,
else it is copied (§12). Links are also written as OSC 8 hyperlinks, which terminals that know them make clickable.

7.4.6 Dependencies tab of a blocked upgrade: the reason, asked of the resolver once (`DETAILS_BLOCKED_REASON`).

### 7.5 Marking (`MARK_*`)

7.5.1 Marks go through `kram/app/marking.py` exactly as in the GUIs, including the questions it asks (shown as
§10.21 question dialogs). The top line counts the marks; the Marked status entry lists them.

7.5.2 Mark upgrades by advisory kind (`MARK_UPGRADE_BY_ADVISORY`): Edit → Mark Upgrades in the menu, and `U` opens
the same list when there are advisories (`MARK_UPGRADE_SPLIT_BUTTON` has no button in a terminal: that list is its
place).

### 7.6 Search (`SEARCH_*`)

7.6.1 `/` opens the search as a modal dialog at the top of the screen (T12, confirmed 2026-11-24: a dialog, not a
line over the list): a text line, the modes of `kram.core.search`
(`Tab`/`Shift+Tab`, compact form when narrow), a status line, the earlier searches under it (`↓`).

7.6.2 The list behind the popup filters while the text is typed (`SEARCH_FILTER_WHILE_TYPING`), for the name
modes, as `NarrowingSearch` does; the status line says "Filtering as you type: 132 packages". Provides and File ask
dnf, only on `Enter` ("dnf looks this up when you press Enter").

7.6.3 `Enter` keeps the search, as the GUIs' search field does (`Browser._on_search_enter`): the list stays
filtered by the sidebar's entry and the search together (a search typed in Installed stays within Installed), the
search goes into the history (Search results), the sidebar stays on its entry, the dialog closes, the list keeps
the ranked order and gets the focus. `Enter` on an empty field drops the search. `Esc` closes and puts back the
list as it was before the dialog opened. While the dialog is open nothing goes into the history by itself: only
`Enter` keeps a search, so that `Esc` can undo everything.

7.6.4 The search text, the mode and the history of the GUIs (`kram/app/search.py`; one history of 30 searches,
each with its mode) apply, under the GUIs' settings keys.

### 7.7 Menus (`MENU_*`)

7.7.1 `m`/`f9` opens the menu popup in the middle: the menus of `menu_bar()` on the left, the entries on the right
with their TUI key (§6.6); submenus open in place with a `← back` line; preferences as `[x]` entries;
dynamic menus (Downgrade to Version, `MENU_DOWNGRADE_SUBMENU`) fill when opened. `←`/`→` move between the columns,
`Enter` runs, `Esc` closes. Disabled entries are dim and say why on the status line of the popup.

7.7.2 The row's context menu (`.`) is `table_menu()` as a one-column popup next to the cursor row.

7.7.3 Settings in the menu come from the registry (`SETTINGS_REGISTRY`); TUI-only settings (§13) are added after
them, then Colours… (§10.17).

## 8. Widgets of our own

8.1 `Button`, `CheckBox`: §4.3. Both are one line, focusable, pressed with `Enter`/`space`/click; disabled ones are
skipped by `Tab`.

8.2 `ChoiceList`: a short modal list (views, tabs, sort columns, schemes, advisory kinds) with a double border, the
current item highlighted, `Enter` picks, `Esc` closes.

8.3 `hint()`: builds §4.5 hints as `rich.text.Text` (Textual's markup has no working escape for `[`).

8.4 No Textual widget is used with its default look where §4 says otherwise: `Button`, `Checkbox`, `SelectionList`,
`RadioSet`, `Switch`, `Tabs`/`TabbedContent` are not used.

## 9. Colours

9.1 **No colour is written in the code** (T16). Every colour is a role of the `Palette` widget; widgets' CSS uses
theme variables; text drawn in Python asks `role(name)`. A scheme change redraws everything at once, with no
restart.

9.2 Roles and their two rule sets:

| Role | High colour | 16 colours (`App:ansi`) | Used for |
|---|---|---|---|
| muted | `$text-muted` | foreground, dim | counts, versions in documents, hints' words, placeholders |
| rule | `$border-blurred` | `$border-blurred` | separators |
| key | `$accent`, bold | `$warning`, bold | keys in hints |
| current | reverse, bold | reverse, bold | current tab, mode |
| header | `$text-muted`, bold | foreground, bold dim | list and table headers |
| cursor | `$block-cursor-*` | reverse, bold | focused cursor row |
| cursor-blurred | `$block-cursor-blurred-*` | underline | unfocused cursor row |
| upgradable | `$warning` | `$warning` | upgradable glyph, advisories |
| installed / ok | `$success` | `$success` | installed glyph, builds ✓ |
| marked | `$accent`, bold | `$accent`, bold | mark glyphs, ticked boxes, changes not applied |
| info | `$primary`, bold | `$primary`, bold | upgrade section, links |
| danger | `$error`, bold | `$error`, bold | removal, warnings, builds ✗ |
| badge | `$error`, reverse bold | `$error`, reverse bold | ROOT |
| frame | `$foreground` 30% | `$border-blurred` | inactive panel borders |
| frame-focus | `$accent` | `$accent` | focused panel, modal borders |

9.3 In 16 colours nothing is blended with transparency (it shows as a solid fill or vanishes): modal screens have
a `transparent` background, so the window stays in sight under them; the footer, text fields and checkboxes use
plain theme colours (T19).

9.4 Schemes (Settings → Colours…, §10.17), saved:

| Scheme | Kind | Notes |
|---|---|---|
| Terminal (default) | 16 colours | `textual-ansi`: the terminal's palette, background and text; light and dark follow the terminal, live. |
| Midnight | 16 colours | blue background, as mc. |
| Console | 16 colours | black background, green accents. |
| Textual dark / light, Nord, Gruvbox, Solarized light, Tokyo Night | high colour | Textual's themes. |

A 16-colour scheme of our own is a `Theme` whose colours are all ANSI names; Kram sets `App.ansi_color` for it
(Textual does only for `textual-ansi`). Textual's command palette theme change is followed too.

9.5 Meaning never by colour alone: glyphs (§7.3.4), words ("Not applied yet: …"), `*` after changed rows.

9.6 `NO_COLOR` set: the Terminal scheme with every role's colour dropped (bold, dim, reverse, underline stay).
Not UTF-8 (`LANG=C`, the Linux console without a Unicode font): borders `ascii` (`+-|`), arrows `<- ->`, glyphs as
letters (§7.3.4), ellipsis `...`.

## 10. Dialogs

General: modal screens (§6.1), double border, title top-left, hints bottom-right, buttons bottom-right in the
order of the GUIs, the default one focused. Width 90% up to 110 columns unless said; height to content up to 90%;
what does not fit scrolls as one area between the header lines and the buttons. Buttons that do not fit on one
line wrap by group onto a second line (`ButtonBar`). Narrow terminals drop columns,
not words: each dialog says which. Each dialog is the view of a presenter of `kram/app` through its view protocol;
it holds no logic of its own.

| § | Dialog | Presenter / protocol | Features |
|---|---|---|---|
| 10.1 | Apply changes | `apply_review.ApplyReview` / `ApplyReviewView` | `DIALOG_APPLY*`, `MARK_APPLY_BUTTON` |
| 10.2 | Progress | `progress.Progress` / `ProgressView` | `DIALOG_PROGRESS*` |
| 10.3 | Administrator rights | `kram/tui/root.py` | `SYSTEM_POLKIT` |
| 10.4 | Repositories | `repos.Repos` / `ReposView` | `DIALOG_REPOSITORIES*` |
| 10.5 | Mirrors | `mirrors` | `DIALOG_MIRRORS*` |
| 10.6 | COPR | `copr.CoprProjects` / `CoprView` | `DIALOG_COPR*` |
| 10.7 | Transaction history | `history` | `DIALOG_HISTORY*` |
| 10.8 | Install package file | `install` | `DIALOG_INSTALL_FILE*`, `INSTALL_FILE_*` |
| 10.9 | Cleanup | `cache` | `DIALOG_CLEANUP*` |
| 10.10 | Custom filters | `custom_filters`, `filters_edit` | `DIALOG_CUSTOM_FILTERS*` |
| 10.11 | Update notifications | `notifier` | `DIALOG_NOTIFICATIONS*` |
| 10.12 | Fedora N | `upgrade`, `release_watch` | `RELEASE_*` |
| 10.13 | About | | `DIALOG_ABOUT_TOOLKIT` |
| 10.14 | What's New | `whats_new` | `DIALOG_WHATS_NEW*` |
| 10.15 | Save / read markings, export CSV | `markings` | `MARKINGS_*` |
| 10.16 | Conflicts | `apply_review` | `DIALOG_APPLY_CONFLICTS` |
| 10.17 | Colours | `palette` | §9.4 |
| 10.18 | Columns | `columns` | `LIST_COLUMNS` |
| 10.19 | Quit | `status` | `WINDOW_CLOSE_PENDING` |
| 10.20 | Keys | | `WINDOW_KEYBOARD_ONLY` |
| 10.21 | Question / message | `ports.Question` | every question of the presenters |

10.1 **Apply changes.** Summary line (counts by kind, download size, free space on the filesystems it touches), the
removal warning of `removal_warning` in the danger role, skipped marks above the list (`DIALOG_APPLY_SKIPPED`), the
changes by group of `GROUPS` with their colour role (install: ok, upgrade: info, remove: danger, others: muted):
name, versions (`old → new`), size, reason. Recommendations as `[x]` checkboxes; unticking resolves again, with
"Resolving…" on the summary line meanwhile (`DIALOG_APPLY_RECOMMENDATIONS`). `[ ] Download packages only`
(`DIALOG_APPLY_DOWNLOAD_ONLY`). The `dnf5` command, muted, wrapped, `y` copies it (`DIALOG_APPLY_COMMAND`). Buttons
`< Apply >` (`ctrl+a`) and `< Cancel >`; Apply is off when the disk cannot hold the change, with the reason on the
summary line (`DIALOG_APPLY_FREE_SPACE`). When nothing can be done: the problem and `< Undo what is possible >`,
`< Show locked packages >` (`DIALOG_APPLY_CANNOT_APPLY`). Narrow: rows show name, resulting version, size.

10.2 **Progress.** Stage line bold; download bar; for a transaction the package bar; both full width (T17) with
their labels above. The log (`DIALOG_PROGRESS_LOG`): the last lines under the bars, `l` opens the whole log with
timestamps in a scrolling area. `[x] Close when finished successfully`, remembered (`DIALOG_PROGRESS_AUTO_CLOSE`).
While the helper has the request, `Esc` and quit do nothing and the hint says so (`esc not while it runs`,
`DIALOG_PROGRESS_CLOSE_LOCK`); before that, while authentication runs, `Esc` stops (the helper has no cancel
operation). Outcomes of authentication (cancelled, not authorized, pkexec missing) show as the dialog's error stage
with `< Close >`; a cancel the user chose shows nothing more. No Close button until done. The OpenPGP key question is a §10.21 question over it
(`DIALOG_PROGRESS_KEY_QUESTION`). Waiting for a desktop's polkit window shows "Waiting for authentication… Your
desktop asks for the password in its own window."

10.3 **Administrator rights**: §11.3.

10.4 **Repositories.** Filter line at the top (`DIALOG_REPOSITORIES_FILTER`). Table: On (`[x]`), Repository,
Name, Packages, Prio, Origin, Mirror (`DIALOG_REPOSITORIES_MIRROR_COLUMN`), Metadata age. `space` turns a
repository on or off; changes not applied are bold with `*` and listed under the table ("Not applied yet: turn on
…; turn off …"). `[ ] Show debuginfo and source repositories` (`ctrl+d`). Buttons: `< Packages >`, `< Mirrors… >`
(off with its reason for a repository with one address), `< Remove file… >` (the user's own files; the question
names every repository of the file and the packages from them), `< Apply >` (`ctrl+a`, needs root). Removals and
mirror changes run over the dialog, which then shows the new state (`*_IN_PLACE`). Closing with changes not applied
asks first. Narrow: Name and Metadata are dropped.

10.5 **Mirrors** (over Repositories): the mirrors of the metalink, In use bold; `< Test speed >` / `< Stop >`, sorted by speed once the test is
done (as `Mirrors.lines` does: rows do not move under the cursor meanwhile); `< Use selected mirror >` (asks about an out-of-date or plain http mirror), `< Automatic >`,
`[ ] Fastest mirror for every repository`. All run over the dialog, which stays open.

10.6 **COPR.** "On this system" table (On, Project, Packages, Installed), or "No COPR projects yet. Search for one
below." A search line (`Enter`), its status line, results (Project, Builds for this system: `✓ chroot` ok / `✗`
danger, Description). Buttons `< Packages >`, `< Disable >`, `< Remove… >` (asks, with Show packages when installed
packages come from it), `< Enable >` (`ctrl+e`; a result, or an `owner/project` typed in the line; asks first when it
has no build for this Fedora). Network errors on the status line, with the retry key.

10.7 **Transaction history.** Filter line (package name); transactions (id, date, action, count); the selected
one's packages below. `< Mark changes to undo >` (`DIALOG_HISTORY_UNDO`); `Enter` on a package selects it in the
window and closes the history (`DIALOG_HISTORY_OPEN_PACKAGE`).

10.8 **Install package file.** From File → Open Package File… (a path line with `Tab` completion; the last folder
remembered), from `kram-tui file.rpm` (the installer alone, §15.2), or from a path pasted into the window
(`INSTALL_FILE_DROP`: a terminal drop pastes the path). What the file does, its recommendations as `[x]`, the
`sudo dnf5 install <file>` line, the `rpm -V` check before a reinstall with what it repairs.

10.9 **Cleanup.** Caches (size, files, `< Clean >`, `< Download again >`); leftover configuration files (path, date,
size); `< Compare >` shows a diff with `+`/`-` lines in ok/danger roles; `< Delete unused >` asks; `< Search all
folders >` needs root.

10.10 **Custom filters.** List of filters; editor: name, Match all / any (`(•)` choices), conditions as rows of
field, operator, value; live count "Matches 1,234 packages"; New Filter from Current View pre-fills it.

10.11 **Update notifications.** The settings of the tray checker (shared with the GUIs), stale-data days, Fedora's
timer with `< Turn on >` (needs root) and its state.

10.12 **Fedora N.** The dialog of `kram/app/upgrade.py`: COPR builds check with its log and `< Cancel >`, release
notes and guide links (§7.4.5), and the command of the upgrade tool to run.

10.13 **About**: Kram's version, "Terminal front end, Textual X.Y" (`DIALOG_ABOUT_TOOLKIT`), links, `< What's new >`.

10.14 **What's New** (over About): the release notes, newest first, scrolling.

10.15 **Markings / CSV**: a path line with completion and the overwrite question.

10.16 **Conflicts**: the installed packages that conflict with the marks, offered for removal, then Apply; when
Kram's own front end is among them, it says Kram will close after the transaction.

10.17 **Colours**: the schemes of §9.4 as a `ChoiceList`; the window behind changes while the cursor moves (a
preview); `Enter` keeps, `Esc` goes back.

10.18 **Columns**: `[x]` per hideable column, `alt+↑ ↓` reorders, `< >` on a row narrows / widens; saved.

10.19 **Quit**: only when something is pending or running (`WINDOW_CLOSE_PENDING`): marks not applied ("Quit and
lose 16 marks?", `< Quit >` / `< Cancel >`, Cancel focused; confirmed 2026-11-24), a transaction running (quitting
is refused, as in the GUIs). With nothing pending `q` quits at once.

10.20 **Keys** (`?`): the keys of the focused scope and the window, two columns, from the bindings themselves.

10.21 **Question / message**: the `Question` of `kram/app/ports.py`: title, text, its buttons; the default button
focused; `Esc` is the cancel answer when there is one.

## 11. Root

11.1 The helper (`kram/helper/kram_helper.py`) runs as root for the session, started once, as in the GUIs.

11.2 **Kram runs as root** (euid 0): the helper starts without pkexec. The top line shows the `ROOT` badge and
"changes need no password". No warning dialog. On Fedora `sudo` sets `HOME=/root` with and without `-i` (spike T3),
so `sudo kram-tui` would see root's settings. With `SUDO_USER` set, Kram reads the invoking user's settings (from
their home, `pwd.getpwnam`) and **writes none**: a file written as root into the user's home would end up root's.
Changes made under sudo last for that run; Settings says so in one muted line. (Proposed, see §18.5.)

11.3 **Not root**, at the first request that needs root:
1. Start pkexec **in a new session, without a controlling terminal** (`start_new_session=True`, stdin
   `/dev/null`), on a worker thread, so that polkit's text agent cannot write over the screen. With a desktop agent,
   its window asks. "Waiting for authentication… Your desktop asks for the password in its own window." shows only
   when pkexec has not answered after 0.3 s: without an agent it fails in 0.02–0.07 s (spike T3), and a dialog that
   flashes up and away is noise.
2. pkexec ends with exit 127 and a message that names the **authentication agent** (polkit 127 says "Error creating
   textual authentication agent: Error opening current controlling terminal for the process (`/dev/tty`)"; older
   ones "No authentication agent found"): there is no agent. Kram shows **Administrator rights**: what needs root,
   that Kram steps aside and polkit asks in this terminal, that it asks once per session, and that `sudo kram-tui`
   asks no password. `< Continue >` / `< Cancel >`.
3. On Continue: `App.suspend()` (the terminal is the shell's), one line "Kram needs administrator rights. Kram comes
   back when you have answered.", pkexec on the terminal, then Kram resumes and goes on.
4. **Ctrl+C at the prompt ends pkexec, not Kram**: while pkexec runs, Kram's SIGINT handler is one that does
   nothing (a handler, not `SIG_IGN`, which pkexec would inherit across exec). pkexec dies of SIGINT; Kram comes
   back and says "Authorization was cancelled".
5. **polkit's text agent takes one password**: a wrong one ends pkexec at once with exit 127 and "Not authorized"
   (spike T3). Kram comes back with **Not authorized**: `< Try again >` (back to step 3) / `< Cancel >`.
6. Exit 126 (dismissed in a desktop window): the request is cancelled, a message says so; nothing else changes.
7. pkexec missing: "Could not start pkexec. Is polkit installed?" (the existing text).
8. A dialog that follows another starts from the first one's dismissal callback, never right after `dismiss()`:
   Textual 8 pops a dismissed screen later, and a screen pushed meanwhile lost the focus or the screen froze one run
   in three (spike T3).

11.4 A second Kram (any front end) with the helper busy gets `BUSY` ("Another operation is still running…").

11.5 Spike T3 (2026-11-24, `scripts/spikes/t3_root.sh`, `t3_pty.py`) confirmed steps 1–5 and 8 in a Fedora container
with systemd and polkit 127, a user in `wheel` and a pseudo-terminal as SSH gives one, on Textual 4.0.0 and
8.1.1: 24 of 24 checks, five runs in a row. Still to check by hand: the desktop agent's window with no terminal
(KDE, GNOME), and the Linux console.

## 12. System

12.1 A desktop is there when `WAYLAND_DISPLAY` or `DISPLAY` is set and `xdg-open` exists.

12.2 Web links and Show in File Manager (`SYSTEM_WEB_LINKS`, `SYSTEM_FILE_MANAGER`) use `xdg-open` /
`kram.core.proc` with a desktop; only `http(s)` addresses are followed. Without one: the address is copied (§12.3)
and the status line says so; Show in File Manager is off with "No desktop to show it in".

12.3 Copy uses the terminal's clipboard (OSC 52, Textual's `copy_to_clipboard`); the status line confirms "Copied".
Terminals that refuse OSC 52 lose nothing else.

12.4 Single instance (`INSTANCE_*`): terminals cannot raise each other, so every `kram-tui` runs on its own;
`kram-tui --upgradable` opens on the Upgradable filter. The dnf lock and the helper's `BUSY` keep two instances
from changing the system at once.

## 13. Settings

13.1 Shared settings come from the registry `kram/app/preferences.py` and `kram/core/settings.py` (the same file as
the GUIs). A setting with a toolkit other than "tui" is ignored. Settings meant for every front end are marked for "qt" and "gtk" today
(`BOTH`); the step that builds the TUI's Settings menu adds "tui" to those that apply (Status click, Watch
releases).

13.2 TUI settings (toolkit "tui"): colour scheme (default Terminal); centre scrolling (on); status glyphs (automatic: symbols on UTF-8, letters otherwise / letters); sidebar width (28); details height (12); pinned panels (both); columns (order, shown, widths); progress
auto-close (shared with the GUIs' meaning); confirm quit with marks (on).

13.3 Saved on change, not on exit (a terminal may be closed under Kram).

## 14. Quality

14.1 **Speed** (CPU, on the machine of `TUI_FRONTEND.md` §11, 70k rows): a cursor or page step ≤ 16 ms at 160×50;
drawing the visible lines ≤ 3 ms; a filter or view change ≤ 100 ms; a sort ≤ 150 ms; first frame after the catalog
≤ 300 ms. Memory: the catalog + ≤ 40 MB.

14.2 **Tests** (pytest, in the `kram-test` container, Textual's `run_test`/`Pilot`, no terminal): every feature
SUPPORTED for "tui" has a test marked `@pytest.mark.feature(Feature.X, front="tui")` (`tests/test_parity.py`).
Layout tests assert focus, shown panels, cursor and scroll, as the spikes print them. Run on Textual 4.0 and 8.1.

14.3 **Screenshots**: a `shots` command keeps the spikes' screenshot cases (wide, narrow, tiny, every dialog, every
scheme); reviewed by eye before a release.

14.4 **Terminals** checked by hand before the first release: Konsole, GNOME Terminal / Ptyxis, kitty, foot,
Alacritty, xterm, tmux and screen inside one of them, SSH, the Linux console (`TERM=linux`). Each with a light and a
dark profile for the Terminal scheme.

14.5 **Translations**: every string through `kram.i18n`; widths measured in cells (`cell_len`), so CJK labels cut
right; no string concatenation that breaks word order.

## 15. Packaging and start

15.1 `packaging/kram.spec` gains the `kram-tui` subpackage (§2.2). `kram-common`'s files are unchanged.

15.2 `kram-tui [--upgradable] [FILE.rpm]`. With a file: the installer alone (§10.8), Kram ends when it closes.
`--version`, `--help`. Exit status 0, or 1 on a failed catalog load.

15.3 Man page `kram-tui.1` with the keys of §6.5. No desktop file.

## 16. Parity

Each feature of `kram/app/parity.py` in the terminal. **S** = SUPPORTED when done, **P** = PARTIAL (note), **N** =
NOT_INTENDED (reason). The TUI column of `parity.py` is updated from this table when the work starts: entries marked
N or P here that are PLANNED there change with the note given.

| Feature | In the terminal | |
|---|---|---|
| DETAILS_ADVISORIES_TAB | tab only when there are advisories; `! advisories` in compact form | S |
| DETAILS_BLOCKED_REASON | §7.4.6 | S |
| DETAILS_CHANGELOG | Changelog tab, scrolling | S |
| DETAILS_DESCRIPTION | description; homepage as a link | S |
| DETAILS_FILES_COPY_PATH | `y`, OSC 52 | S |
| DETAILS_FILES_FILTER | `/` in the tab; matches bold | S |
| DETAILS_FILES_LIST | `f` switches tree / list | S |
| DETAILS_FILES_SHOW_IN_FM | `o`, desktop only | P: no desktop, no file manager |
| DETAILS_FILES_TREE | tree with `├─ └─`, every folder open | S |
| DETAILS_LINKS | `Tab`/`Enter`, OSC 8 | S |
| DETAILS_REMEMBER_TAB | `TabChoice`, saved | S |
| DETAILS_TABS | §7.4.1 | S |
| DETAILS_VERSIONS | table | S |
| DIALOG_ABOUT_TOOLKIT | "Terminal front end, Textual X.Y" | S |
| DIALOG_APPLY … DIALOG_APPLY_SKIPPED | §10.1 | S |
| DIALOG_APPLY_CONFLICTS | §10.16 | S |
| DIALOG_CLEANUP … DIALOG_CLEANUP_SEARCH_ALL | §10.9 | S |
| DIALOG_COPR … DIALOG_COPR_REMOVE_QUESTION | §10.6 | S |
| DIALOG_CUSTOM_FILTERS … _NEW_FROM_VIEW | §10.10 | S |
| DIALOG_HISTORY … DIALOG_HISTORY_UNDO | §10.7 | S |
| DIALOG_INSTALL_FILE … _RECOMMENDATIONS | §10.8 | S |
| DIALOG_MIRRORS … DIALOG_MIRRORS_SPEED_TEST | §10.5 | S |
| DIALOG_NOTIFICATIONS … _STALE_DAYS | §10.11 | S |
| DIALOG_PROGRESS … DIALOG_PROGRESS_LOG | §10.2 | S |
| DIALOG_REPOSITORIES … _UPDATES_IN_PLACE | §10.4 | S |
| DIALOG_WHATS_NEW, _OVER_ABOUT | §10.14 | S |
| ICON_NON_PIXELATED | glyphs, not icons | N (already) |
| INSTALL_FILE_ARGUMENT | `kram-tui file.rpm` | S |
| INSTALL_FILE_DROP | a pasted path of an `.rpm` (a terminal drop pastes it) | P: drop = paste |
| INSTALL_FILE_OPEN_MENU | path line with completion | S |
| INSTANCE_ACTIVATION_TOKEN | — | N: a terminal cannot raise another (§12.4) |
| INSTANCE_TRAY | `--upgradable`; the tray opens the GUI | P: the tray starts the GUI front end |
| LIST_COLUMNS | §10.18 | S |
| LIST_CONTEXT_MENU | `.`, `Shift+F10`, right click | S |
| LIST_DOUBLE_CLICK_MARK | `space`; double click with a mouse | S |
| LIST_EMPTY_EXPLANATION | §7.3.8 | S |
| LIST_LOCK_PADLOCK | flag `L` | S |
| LIST_MULTI_SELECT | §7.3.6 | S |
| LIST_ROW_TINT | §7.3.5 | P: 16 colours tint glyph and name, not the row |
| LIST_SORT | `s`/`S` | S |
| LIST_STATUS_CLICK | `space`, click on `S` | S |
| LIST_VERSION_LOCK | `=` | S |
| MARKINGS_CSV_EXPORT, MARKINGS_FILE | §10.15 | S |
| MARK_APPLY_BUTTON | `a` → §10.1 | S |
| MARK_INSTALL_REMOVE | `+`/`Ins`, `-`/`Del` | S |
| MARK_UNMARK_ALL | `Z` (`ctrl+shift+z` cannot be told apart) | S |
| MARK_UNMARK_ONE | `z`, `ctrl+z` | S |
| MARK_UNNEEDED | menu | S |
| MARK_UPGRADE_ALL | `U`, `ctrl+u` | S |
| MARK_UPGRADE_BY_ADVISORY | menu, `U` list | S |
| MARK_UPGRADE_SPLIT_BUTTON | the `U` list | P: no split button in a terminal |
| MENU_ACCELERATORS | TUI keys shown | S |
| MENU_BAR | popup (T12) | P: a popup, not a permanent bar |
| MENU_DOWNGRADE_SUBMENU | dynamic submenu | S |
| MENU_HAMBURGER, MENU_ICONS | — | N (already) |
| MENU_PACKAGE, MENU_SIDEBAR | §7.7 | S |
| RELEASE_BUTTON | top line `Fedora N is out: r` | S |
| RELEASE_DIALOG, RELEASE_WATCH | §10.12 | S |
| SEARCH_BAR | the search dialog (T12) | P: a dialog, not a bar |
| SEARCH_FILTER_WHILE_TYPING, SEARCH_MODES | §7.6 | S |
| SETTINGS_MENU_BAR, SETTINGS_TOOLBAR_STYLE | — | N (already) |
| SETTINGS_REGISTRY | §13.1 | S |
| SETTINGS_STATUS_CLICK | what `space` does on `S` follows it | S |
| SETTINGS_WATCH_RELEASES | the top line's notice follows it | S |
| SIDEBAR_COUNTS … SIDEBAR_VIEWS | §7.2 | S |
| SIDEBAR_SECTION_ICONS | — | N (already) |
| SYSTEM_FILE_MANAGER, SYSTEM_WEB_LINKS | §12.2 | P: only with a desktop; else copied |
| SYSTEM_POLKIT | §11 | S |
| SYSTEM_THEME_FOLLOWS_DESKTOP | — | N (already); the Terminal scheme follows the terminal |
| TRANSLATIONS_CATALOGS | §14.5 | S |
| WINDOW_CLOSE_PENDING | §10.19 | S |
| WINDOW_FRACTIONAL_SCALE | — | N (already) |
| WINDOW_HEADER_BUTTONS | the keys `f5 a U` (in the menu and the Keys dialog) | P: keys, not buttons |
| WINDOW_KEYBOARD_ONLY | everything | S |
| WINDOW_PANES_SAVED | panel sizes and pins saved | S |
| WINDOW_STATUS_BAR | the top line (§5.4) | S |

## 17. Phases

| Phase | Done when |
|---|---|
| 0. Spikes | T1, T2 done (2026-11-23/24); **T3** (root, §11.5) done and recorded |
| 1. Window | §5–§9 over the real catalog: list, sidebar, details (Description, General, Versions), search, menu, colours, small-terminal screen; tests of §14.2 for them |
| 2. Changes | marking (§7.5), Apply (§10.1), Progress (§10.2), root (§11), Question (§10.21); a real upgrade done from the TUI in a VM |
| 3. Dialogs | §10.4–§10.20 and the remaining detail tabs |
| 4. Release | §16 all S/P/N with notes, parity tests green on 4.0 and 8.1, §14.4 checked, man page, `kram-tui` in the spec and COPR |

## 18. Decisions on the open questions (2026-11-24)

1. Status glyphs: symbols (`■ □ ▲ …`) when the terminal speaks UTF-8, letters (`i p u …`) when it does not; a
   setting can ask for letters always (§4.4, §7.3.4, §9.6, §13).
2. Search stays a modal dialog at the top of the screen; it filters the list behind it while typing (§7.6).
3. `U` (Mark All Upgrades) and `Z` (Unmark All) stay: both only change marks and can be undone (§6.5).
4. `q` asks before quitting when marks are not applied (§10.19).
5. **Open**: under `sudo`, read the invoking user's settings and save nothing (§11.2, proposed), or use root's own?
