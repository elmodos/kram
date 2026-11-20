%global appid io.github.elmodos.Kram
%global base_version 0.11.1

Name:           kram
# A tagged release (v%%{base_version}) is plain %%{base_version}. Any other commit gets a snapshot from
# .copr/Makefile, ^YYYYMMDDHHMMSSgitHASH (UTC commit time): newer than the release it follows, older than the next one.
Version:        %{base_version}%{?snapshot}
Release:        1%{?dist}
Summary:        Synaptic-style package manager for Fedora

License:        MIT
URL:            https://github.com/elmodos/kram
Source0:        %{url}/archive/v%{base_version}/%{name}-%{base_version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  gettext
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
BuildRequires:  systemd-rpm-macros
# for the test suite (python3-pyside6: the UI modules are imported and the icons rendered offscreen)
BuildRequires:  python3-pytest
BuildRequires:  python3-libdnf5
BuildRequires:  python3-rpm
BuildRequires:  python3-pyside6
BuildRequires:  python3-gobject-base

Requires:       python3-libdnf5
Requires:       python3-rpm
# pulls in Qt itself (qt6-qtbase, qt6-qtsvg for the SVG icons) through its library dependencies
Requires:       python3-pyside6
Requires:       polkit
# "dnf5 copr" and "dnf5 config-manager" (COPR and repository changes)
Requires:       dnf5-plugins
Requires:       hicolor-icon-theme
# the tray update checker's icon: a StatusNotifierItem over Gio D-Bus, lighter than Qt
Requires:       python3-gobject-base
# translations of Qt's standard buttons (Yes, No, Cancel…) in the UI language
Recommends:     qt6-qttranslations

%description
Kram is a package manager in the style of Synaptic, built on libdnf5. It lists every package in the enabled
repositories with its status, origin (Fedora, COPR, third-party), versions and size; has ranked search by
name, description, provides and files; marks changes, previews the whole transaction and applies it. It also
enables and disables repositories and manages COPR projects.

%prep
%autosetup -n %{name}-%{base_version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel
for po in po/*.po; do
    lang=$(basename "$po" .po)
    mkdir -p "build-locale/$lang/LC_MESSAGES"
    msgfmt --check -o "build-locale/$lang/LC_MESSAGES/%{name}.mo" "$po"
done

%install
%pyproject_install
# the helper's work directory: root only, see LOCAL_DIR in kram/helper/kram_helper.py
install -d -m 0700 %{buildroot}%{_localstatedir}/cache/kram
%pyproject_save_files -l kram
# the root helper: started by pkexec at the path the polkit policy names
install -Dpm 0755 kram/helper/kram_helper.py %{buildroot}%{_libexecdir}/kram-helper
install -Dpm 0644 data/%{appid}.policy %{buildroot}%{_datadir}/polkit-1/actions/%{appid}.policy
install -Dpm 0644 data/%{appid}.desktop %{buildroot}%{_datadir}/applications/%{appid}.desktop
# Xfce only (OnlyShowIn): puts Kram in the Settings Manager's System section
install -Dpm 0644 data/%{appid}.xfce-settings.desktop %{buildroot}%{_datadir}/applications/%{appid}.xfce-settings.desktop
install -Dpm 0644 data/%{appid}.metainfo.xml %{buildroot}%{_metainfodir}/%{appid}.metainfo.xml
install -Dpm 0644 data/%{appid}.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
# the tray update checker: systemd user units, none enabled by default (Kram's settings turn it on)
install -Dpm 0644 -t %{buildroot}%{_userunitdir} data/systemd/kram-*
# its tray icons, in hicolor so that every icon theme finds them
install -Dpm 0644 -t %{buildroot}%{_datadir}/icons/hicolor/scalable/status data/icons/%{appid}-update-*.svg
# and once more where the tray icon tells the panel to look (IconThemePath): a panel started before Kram was
# installed has not seen the hicolor ones
install -Dpm 0644 -t %{buildroot}%{_datadir}/kram/icons data/icons/%{appid}-update-*.svg
mkdir -p %{buildroot}%{_datadir}/locale
cp -a build-locale/. %{buildroot}%{_datadir}/locale/
%find_lang %{name}

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{appid}.desktop
desktop-file-validate %{buildroot}%{_datadir}/applications/%{appid}.xfce-settings.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/%{appid}.metainfo.xml
QT_QPA_PLATFORM=offscreen %pytest

%post
# the user presets ("disable *") leave the update checker off; Kram's settings turn it on per user
%systemd_user_post kram-update-check.timer kram-update-check.path

%preun
# removal: stop and disable it for every logged-in user
%systemd_user_preun kram-update-check.timer kram-update-check.path kram-tray.service

%postun
# upgrade: a running tray icon still has the old code loaded; restart it for every logged-in user
%systemd_user_postun_with_restart kram-tray.service

%files -f %{pyproject_files} -f %{name}.lang
%doc README.md
%dir %attr(0700,root,root) %{_localstatedir}/cache/kram
%{_bindir}/kram
%{_libexecdir}/kram-helper
%{_datadir}/polkit-1/actions/%{appid}.policy
%{_datadir}/applications/%{appid}.desktop
%{_datadir}/applications/%{appid}.xfce-settings.desktop
%{_metainfodir}/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
%{_userunitdir}/kram-update-check.service
%{_userunitdir}/kram-update-check.timer
%{_userunitdir}/kram-update-check.path
%{_userunitdir}/kram-tray.service
%{_datadir}/icons/hicolor/scalable/status/%{appid}-update-*.svg
%{_datadir}/kram/

%changelog
* Fri Nov 20 2026 Modo Ltunzher <offnormal@gmail.com> - 0.11.1-1
- If Kram is closed or crashes during a transaction, the helper now finishes it instead of aborting rpm halfway
- Apply and Refresh can no longer start twice while dependencies are being resolved
- A failed transaction reloads the package list; marks added during a review are kept
- The password is asked for every helper start (polkit auth_admin, no longer kept for 5 minutes)
- The installer opens only http and https links from a package file
- A package whose signature could not be checked is no longer shown as unsigned
- History: double-clicking a group row no longer resets the package list; undo explains kernels and group reasons correctly
- Marking thousands of packages at once is fast
- Plural forms in the history and status bar follow the language
- The update checker notices repositories enabled or disabled in Kram

* Fri Nov 20 2026 Modo Ltunzher <offnormal@gmail.com> - 0.11.0-1
- History: File → Transaction History shows what dnf installed, upgraded and removed, and when
- History: Mark Changes to Undo marks the changes that take a transaction back, for review before Apply
- History: double-clicking a package closes the history and selects the package in the list
- History: groups and environments a transaction changed are listed with its packages
- History: a transaction that changed groups or environments is undone whole, as dnf5 history undo does
- History: when a transaction cannot be undone whole, what is still possible can be undone (--skip-unavailable)
- Package: Show in History lists the transactions that changed the selected package
- Sidebar: an Environments view (KDE Plasma Workspaces, Fedora Workstation, …), each environment unfolds into its groups
- Groups: install, upgrade or remove a group or environment at once from its menu, after the review, instead of marking it
- Groups: optional packages are in italics in the list, and a group can be installed with them
- Groups: no removal for the hidden groups the system is built on (core, standard)
- Groups: the review explains when a group change touches no package and dnf only records the group
- Applying changes: the review checks free disk space and says how much is missing
- Applying changes: the review warns before removing the desktop you are using
- Sidebar: right-click a repository in the Origin view to refresh only its metadata
- Package list: kernel upgrades no longer show as upgrades that cannot be installed, and Mark All Upgrades marks them again
- Tray: the update count includes kernel upgrades
- Package list: an upgrade that cannot be installed says why when the row is selected
- Sidebar: Status → Cannot be upgraded now lists the upgrades dnf leaves out, with the reason on the Dependencies tab
- Package: Why It Cannot Be Upgraded opens the reason for an upgrade that cannot be installed now
- Edit: Mark All Upgrades says where to see the upgrades it left out
- Details: the Dependencies tab of kernel-core no longer freezes the window; long lists show the first 1000 items
- Sidebar: an empty Status entry disappears once another entry is selected

* Thu Nov 19 2026 Modo Ltunzher <offnormal@gmail.com> - 0.10.0-1
- Package list: lock a package at its installed version (Package → Lock Version) and unlock it again
- Package list: a padlock marks locked packages, and the upgrade a lock holds back is shown greyed
- Sidebar: Status → Locked versions; empty, it tells how to lock a package
- Package list: an optional Download size column; Size is now Installed size
- File menu: export the listed packages as CSV
- Package list: an empty list says why and links to what would fill it
- F5 reloads, as Ctrl+R does
- Sidebar: nested entries have their icons indented under their parent

* Thu Nov 19 2026 Modo Ltunzher <offnormal@gmail.com> - 0.9.0-1
- Package details: the Files tab shows the files in a folder tree or as a list
- Package details: a filter in the Files tab, with the matched text in bold
- Package details: copy a file's path or show it in the file manager from the Files tab

* Wed Nov 18 2026 Modo Ltunzher <offnormal@gmail.com> - 0.8.5-1
- Progress dialog: dnf's error messages appear in your language where dnf has a translation
- Progress dialog: Kram's own messages there are translated too, such as the dnf5 command being run

* Wed Nov 18 2026 Modo Ltunzher <offnormal@gmail.com> - 0.8.4-1
- Package list: an upgrade that cannot be installed now shows a red cross before its version
- Details: the Dependencies tab of such an upgrade shows why it cannot be installed

* Wed Nov 18 2026 Modo Ltunzher <offnormal@gmail.com> - 0.8.3-1
- Sidebar: "Security updates" and "Bug fix updates" are hidden when there are none

* Wed Nov 18 2026 Modo Ltunzher <offnormal@gmail.com> - 0.8.2-1
- Fix the Fedora Rawhide build: the test run no longer crashes on exit with PySide6 6.12

* Wed Nov 18 2026 Modo Ltunzher <offnormal@gmail.com> - 0.8.1-1
- Repositories and COPR: the Packages column counts distinct packages instead of every built version

* Wed Nov 18 2026 Modo Ltunzher <offnormal@gmail.com> - 0.8.0-1
- Repositories: Show packages filters the list to a repository's packages
- Repositories: Remove… deletes a repository you added yourself, with every repository its file configures
- Origin filters: each Fedora repository (fedora, updates…) is listed on its own
- Cleanup (was Package Cache): lists leftover .rpmnew/.rpmsave configuration files, compares them with the current file and deletes them
- Edit: Mark Unneeded Dependencies for Removal marks what dnf autoremove would remove
- Status filters: Unneeded dependencies also lists the orphaned and upgradable ones that autoremove removes
- Package list: the Repository column shows where an installed package came from when its latest version is in another repository

* Tue Nov 17 2026 Modo Ltunzher <offnormal@gmail.com> - 0.7.3-1
- Tray: upgrades that cannot be installed (such as a new build that needs a missing library) are no longer counted
- Updates: upgrades that cannot be installed now are dimmed, with the reason in the tooltip, and Mark All Upgrades leaves them out

* Tue Nov 17 2026 Modo Ltunzher <offnormal@gmail.com> - 0.7.2-1
- Catalog: after a transaction, Kram waits for another package manager (such as akmods building kernel modules) instead of failing with "Failed to acquire system repo lock"
- Tray: the update check no longer fails while another package manager is running
- Apply changes: the dialog says which marked upgrades cannot be installed and why (such as a missing library), instead of an empty list
- Apply changes: Apply is disabled when nothing is left to do

* Tue Nov 17 2026 Modo Ltunzher <offnormal@gmail.com> - 0.7.1-1
- Packaging: the package builds again for Fedora Rawhide (the test run crashed with PySide6 6.12)

* Tue Nov 17 2026 Modo Ltunzher <offnormal@gmail.com> - 0.7.0-1
- Updates: a coloured dot and an Update type column show which upgrades fix security issues (by severity), bugs or add enhancements
- Updates: an Advisories tab shows what an upgrade fixes, with links to the advisory, the bugs and the CVEs
- Updates: the sidebar lists the security updates and the bug fix updates on their own
- Updates: the arrow next to Mark All Upgrades marks only the security upgrades, only the critical and important ones, or the security and bug fix upgrades
- Custom filters: filter by update type

* Tue Nov 17 2026 Modo Ltunzher <offnormal@gmail.com> - 0.6.1-1
- Tray: clicking the update icon no longer crashes Kram when the icon appeared right after login

* Tue Nov 17 2026 Modo Ltunzher <offnormal@gmail.com> - 0.6.0-1
- Groups: right-click a group to install it, or to upgrade or remove an installed one
- Groups: Upgrade is offered only for groups that have something to upgrade
- Apply changes: groups and the packages they install or remove are listed separately
- Speed: the window no longer freezes for seconds when the cursor lands on a kernel package
- Speed: Provides searches by part of a name or with * are about 20 times faster and keep the window responsive
- Speed: typing a search and clearing it are several times faster in long package lists
- Speed: moving through the list no longer stalls on loading package details

* Sun Nov 15 2026 Modo Ltunzher <offnormal@gmail.com> - 0.5.7-1
- Sidebar: groups show icons from the system icon theme, and installed groups are in bold
- Sidebar: every Status entry has an icon matching the package list's status column

* Sat Nov 14 2026 Modo Ltunzher <offnormal@gmail.com> - 0.5.6-1
- Package files: opening an .rpm file no longer fails with "cannot create directories: Permission denied"

* Sat Nov 14 2026 Modo Ltunzher <offnormal@gmail.com> - 0.5.5-1
- Update notifications: the tray icon appears right after Kram's Reload finds updates, and after waking from sleep

* Sat Nov 14 2026 Modo Ltunzher <offnormal@gmail.com> - 0.5.4-1
- Updates that change a package's architecture (noarch to x86_64, like python3-wcwidth in Fedora 45) now show the new version and install

* Sat Nov 14 2026 Modo Ltunzher <offnormal@gmail.com> - 0.5.3-1
- Xfce: Kram is in the Settings Manager (System section), as "Package Manager"

* Sat Nov 14 2026 Modo Ltunzher <offnormal@gmail.com> - 0.5.2-1
- Fixed a rare crash after Kram finished loading packages or applying changes

* Sat Nov 14 2026 Modo Ltunzher <offnormal@gmail.com> - 0.5.1-1
- Tray: the icon shows the update level right after installing Kram, without restarting the Plasma panel

* Sat Nov 14 2026 Modo Ltunzher <offnormal@gmail.com> - 0.5.0-1
- Tray: an optional icon while updates are available, with how many are security updates
  (Settings > Update Notifications); it downloads nothing, Fedora's dnf-makecache.timer does
- Tray: clicking the icon opens Kram on the upgradable packages
- Kram opens only once: starting it again brings the open window to the front
- Update Notifications: turn Fedora's automatic update check on, and Discover's or GNOME Software's
  update notifier off

* Thu Nov 12 2026 Modo Ltunzher <offnormal@gmail.com> - 0.4.3-1
- Table: an option in Settings makes a click on the status icon mark the likely action (install, upgrade or unmark) instead of opening the menu

* Tue Nov 10 2026 Modo Ltunzher <offnormal@gmail.com> - 0.4.2-1
- Toolbar: the Mark All Upgrades icon no longer looks disabled when there are upgrades to mark
- Repositories: the id and the file path are shown in full, a long path is cut in the middle
- Repositories: every column can be resized and the list scrolls sideways
- Repositories: right-click a file path to copy it or show it in the file manager

* Tue Nov 10 2026 Modo Ltunzher <offnormal@gmail.com> - 0.4.1-1
- Apply dialog: no more "essential package will be removed" warning when only the oldest kernel makes room for a new one
- Apply dialog: package names are no longer cut short by long versions

* Mon Nov 09 2026 Modo Ltunzher <offnormal@gmail.com> - 0.4.0-1
- A toolbar button tells when a new Fedora release is out (Settings > Watch Fedora Releases)
- Its dialog works out what the upgrade would block, remove and need, without changing anything
- The progress bar keeps moving while waiting for a slow server, instead of sitting at 100%

* Mon Nov 09 2026 Modo Ltunzher <offnormal@gmail.com> - 0.3.1-1
- Custom filters: new Provides condition, e.g. application() for packages with a menu entry
- Apply dialog: the equivalent command changes with "Download packages only"

* Mon Nov 09 2026 Modo Ltunzher <offnormal@gmail.com> - 0.3.0-1
- Settings > Package Cache: how much space the package caches take, where they are, and cleaning them,
  including the packages Discover and GNOME Software downloaded and left behind
- Repositories and COPR are greyed out until the package list has loaded
- The progress window stays on top of the COPR dialog that started it
- The progress window no longer says "Waiting for authentication" while metadata downloads

* Sun Nov 08 2026 Modo Ltunzher <offnormal@gmail.com> - 0.2.0-1
- Install a downloaded .rpm file: File > Open Package File, drop it on the window, or Open with Kram;
  shows install, upgrade, downgrade or reinstall, the signature, scripts run as root, what satisfies
  each dependency and a newer version in a repository; reinstalling checks the files first (rpm -V)
- Choose which recommended packages to install, with the size each one adds
- A running package operation elsewhere is reported plainly instead of as a signature error
- Progress: replacing a package is no longer logged as removing it; the bar counts packages
- About: What's New lists the changes of every version

* Fri Nov 06 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.9-1
- Toolbar: monochrome icon for Mark All Upgrades; Properties only in the Package menu
- The package details pane can no longer be collapsed out of sight

* Fri Nov 06 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.8-1
- Marking a package for removal offers to mark the packages that depend on it (at any depth), as
  dnf5 remove would remove them; before, applying failed with "conflicting requests"
- Package list: install reason column (user, group, not recorded, dependency, weak dependency)
- Right-click the list header to hide or show columns

* Fri Nov 06 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.7-1
- Translations: Swedish (first pass, review welcome)

* Thu Nov 05 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.6-1
- Relicensed under the MIT License; the About dialog shows the copyright and license
- Search results: remove a search from the history or clear the whole history (context menu)
- Search field: a funnel icon while the search text filters the list

* Wed Nov 04 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.5-1
- Load the package catalog even when an enabled repository has no metadata ("Failed to set up metadata
  download"); such repositories are listed in the status bar (GitHub issue #1)

* Wed Nov 04 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.4-1
- Translations: Czech, French, German, Italian, Japanese, Korean, Polish, Portuguese (Brazil),
  Simplified Chinese, Spanish (first pass, review welcome)
- Translated desktop entry, AppStream summary and polkit messages

* Wed Nov 04 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.3-1
- Progress dialog: count packages from 1 ("48 of 48" when done) and log each package once

* Wed Nov 04 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.2-1
- Fix "cannot create temporary file: Permission denied" when loading the catalog after a background
  metadata refresh (dnf-makecache.timer)
- %%check also imports the UI and renders the icons; recommend qt6-qttranslations

* Wed Nov 04 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.1-1
- Read the system metadata cache, so Reload shows new packages and the real metadata age
- Custom filters in the sidebar
- Toolbar styles (follow System Settings, compact text beside icons, …) instead of hiding the toolbar
- Sharp status and origin icons on scaled screens (125 %, 150 %, 200 %)

* Wed Nov 04 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.0-2
- Tagged release v0.1.0; git snapshots now use the ^YYYYMMDDgitHASH version suffix
- Release 2 so it is newer than the earlier 0.1.0-1.YYYYMMDDgitHASH snapshot builds

* Tue Nov 03 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.0-1
- First release
