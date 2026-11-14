%global appid io.github.elmodos.Kram
%global base_version 0.5.2

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
%pyproject_save_files -l kram
# the root helper: started by pkexec at the path the polkit policy names
install -Dpm 0755 kram/helper/kram_helper.py %{buildroot}%{_libexecdir}/kram-helper
install -Dpm 0644 data/%{appid}.policy %{buildroot}%{_datadir}/polkit-1/actions/%{appid}.policy
install -Dpm 0644 data/%{appid}.desktop %{buildroot}%{_datadir}/applications/%{appid}.desktop
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
%{_bindir}/kram
%{_libexecdir}/kram-helper
%{_datadir}/polkit-1/actions/%{appid}.policy
%{_datadir}/applications/%{appid}.desktop
%{_metainfodir}/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
%{_userunitdir}/kram-update-check.service
%{_userunitdir}/kram-update-check.timer
%{_userunitdir}/kram-update-check.path
%{_userunitdir}/kram-tray.service
%{_datadir}/icons/hicolor/scalable/status/%{appid}-update-*.svg
%{_datadir}/kram/

%changelog
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
