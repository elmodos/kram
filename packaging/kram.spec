%global appid io.github.elmodos.Kram
%global base_version 0.14.2
# the first version that is split into kram-common + kram-qt + kram-gtk; the single kram package before it is
# obsoleted by kram-qt
%global split_version 0.12.0

Name:           kram
# A tagged release (v%%{base_version}) is plain %%{base_version}. Any other commit gets a snapshot from
# .copr/Makefile, ^YYYYMMDDHHMMSSgitHASH (UTC commit time): newer than the release it follows, older than the next one.
Version:        %{base_version}%{?snapshot}
Release:        1%{?dist}
Summary:        Synaptic-style package manager for Fedora

License:        MIT
URL:            https://github.com/elmodos/kram
# COPR leaves Packager unset (Vendor is "Fedora Copr - user elmodos"); name the person who packages Kram
Packager:       Modo Ltunzher <offnormal@gmail.com>
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
# the GTK front end's tests (tests/test_gtk.py): GTK's own broadway display server (in gtk4) stands in for a desktop
BuildRequires:  python3-gobject
BuildRequires:  gtk4
BuildRequires:  libadwaita >= 1.7
BuildRequires:  gobject-introspection

%global _description %{expand:
Kram is a package manager in the style of Synaptic, built on libdnf5. It lists every package in the enabled
repositories with its status, origin (Fedora, COPR, third-party), versions and size; has ranked search by
name, description, provides and files; marks changes, previews the whole transaction and applies it. It also
enables and disables repositories and manages COPR projects.}

%description %_description

%package        common
Summary:        Synaptic-style package manager for Fedora: files shared by the front ends
Requires:       python3-libdnf5
Requires:       python3-rpm
Requires:       polkit
# "dnf5 copr" and "dnf5 config-manager" (COPR and repository changes)
Requires:       dnf5-plugins
Requires:       hicolor-icon-theme
# the tray update checker's icon: a StatusNotifierItem over Gio D-Bus, lighter than Qt
Requires:       python3-gobject-base
# the single kram package before the split has the same files: without this, "dnf install kram-gtk" over it passed
# the solver and failed in rpm on the file conflicts. kram-qt replaces it (Obsoletes); for GTK, dnf swap kram kram-gtk
Conflicts:      kram < %{split_version}

%description    common %_description

This package has the package management logic, the root helper, the tray update checker and the translations
shared by the front ends, which require it: install kram (the Qt front end, kram-qt) or kram-gtk.

%package        qt
Summary:        Synaptic-style package manager for Fedora: Qt front end
Requires:       kram-common = %{version}-%{release}
# pulls in Qt itself (qt6-qtbase, qt6-qtsvg for the SVG icons) through its library dependencies
Requires:       python3-pyside6
# translations of Qt's standard buttons (Yes, No, Cancel…) in the UI language
Recommends:     qt6-qttranslations
Conflicts:      kram-gtk
# existing installs of the single kram package move to the Qt front end, and "dnf install kram" keeps working
Obsoletes:      kram < %{split_version}
Provides:       kram = %{version}-%{release}
# /usr/bin/kram (%%post)
Requires(post):   alternatives
Requires(postun): alternatives

%description    qt %_description

This package is the Qt front end, for KDE Plasma and other Qt desktops.

%package        gtk
Summary:        Synaptic-style package manager for Fedora: GTK front end
Requires:       kram-common = %{version}-%{release}
# python3-gobject, not -base: the painted icons use cairo
Requires:       python3-gobject
Requires:       gtk4
# Adw.ToggleGroup
Requires:       libadwaita >= 1.7
# the cairo typelib (cairo-1.0.typelib) that Gtk's and Adw's typelibs depend on; nothing above pulls it in
Requires:       gobject-introspection
Conflicts:      kram-qt
# /usr/bin/kram (%%post)
Requires(post):   alternatives
Requires(postun): alternatives

%description    gtk %_description

This package is the GTK 4 and libadwaita front end, for GNOME.

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
# /usr/bin/kram is the GUI front end that is installed: kram-qt and kram-gtk each have a launcher of their own in
# /usr/libexec/kram and point /usr/bin/kram at it with alternatives (%%post). The Qt launcher is the one pyproject's
# gui-scripts entry point generates.
install -d %{buildroot}%{_libexecdir}/kram
mv %{buildroot}%{_bindir}/kram %{buildroot}%{_libexecdir}/kram/kram-qt
cat > %{buildroot}%{_libexecdir}/kram/kram-gtk <<'LAUNCHER'
#!%{python3} -sP
import sys
from kram.gtk.app import main
sys.exit(main())
LAUNCHER
chmod 0755 %{buildroot}%{_libexecdir}/kram/kram-gtk
# owned by both front ends as %%ghost: alternatives makes it a symbolic link, rpm only knows whose it is
touch %{buildroot}%{_bindir}/kram
# the helper's work directory: root only, see LOCAL_DIR in kram/helper/kram_helper.py
install -d -m 0700 %{buildroot}%{_localstatedir}/cache/kram
# the units' enabled state of logged-in users, kept across the replacement of the single kram package (%%pre)
install -d -m 0700 %{buildroot}%{_localstatedir}/lib/rpm-state/kram
# the root helper: started by pkexec at the path the polkit policy names
install -Dpm 0755 kram/helper/kram_helper.py %{buildroot}%{_libexecdir}/kram-helper
install -Dpm 0644 data/%{appid}.policy %{buildroot}%{_datadir}/polkit-1/actions/%{appid}.policy
install -Dpm 0644 data/%{appid}.desktop %{buildroot}%{_datadir}/applications/%{appid}.desktop
# Xfce only (OnlyShowIn): puts Kram in the Settings Manager's System section
install -Dpm 0644 data/%{appid}.xfce-settings.desktop %{buildroot}%{_datadir}/applications/%{appid}.xfce-settings.desktop
install -Dpm 0644 data/%{appid}.metainfo.xml %{buildroot}%{_metainfodir}/%{appid}.metainfo.xml
# the same file for What's New in every front end (kram/core/releases.py): the AppStream one is kram-qt's only
install -Dpm 0644 data/%{appid}.metainfo.xml %{buildroot}%{_datadir}/kram/%{appid}.metainfo.xml
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

# The menu entries, in each GUI front end (identical files, one buildroot): they run /usr/bin/kram, which a front
# end provides.
%global gui_files %{expand:
%{_datadir}/applications/%{appid}.desktop
%{_datadir}/applications/%{appid}.xfce-settings.desktop
}

%global user_units kram-update-check.timer kram-update-check.path kram-tray.service

%pre common
# Replacing the single kram package (< %%{split_version}): rpm erases it after this package is installed, and its
# %%preun disables the user units for every logged-in user, as on removal. Remember which ones were enabled;
# %%posttrans enables them again.
state=%{_localstatedir}/lib/rpm-state/kram/enabled-units
rm -f "$state"
if rpm -q --quiet kram && [ -d /run/systemd/system ]; then
    mkdir -p -m 0700 "${state%%/*}"
    for user in $(systemctl list-units 'user@*' --legend=no | sed -n -r 's/.*user@([0-9]+).service.*/\1/p'); do
        for unit in kram-update-check.timer kram-update-check.path; do
            if SYSTEMD_BUS_TIMEOUT=15s systemctl --user -M "$user@" is-enabled --quiet "$unit" 2>/dev/null; then
                echo "$user $unit" >> "$state"
            fi
        done
    done
fi
:

%post common
# the user presets ("disable *") leave the update checker off; Kram's settings turn it on per user
%systemd_user_post kram-update-check.timer kram-update-check.path

%preun common
# removal: stop and disable it for every logged-in user
%systemd_user_preun %{user_units}

%postun common
# upgrade: a running tray icon still has the old code loaded; restart it for every logged-in user
%systemd_user_postun_with_restart kram-tray.service

%post qt
# the single kram package (< %%{split_version}) had /usr/bin/kram as a file; it is erased only after this
# scriptlet, and as kram-qt owns the path (%%ghost) rpm would leave that file there
[ -L %{_bindir}/kram ] || rm -f %{_bindir}/kram
%{_sbindir}/alternatives --install %{_bindir}/kram kram %{_libexecdir}/kram/kram-qt 20

%postun qt
# removal, also in "dnf swap kram-qt kram-gtk": after kram-gtk's %%post, so /usr/bin/kram moves to kram-gtk here
if [ $1 -eq 0 ]; then
    %{_sbindir}/alternatives --remove kram %{_libexecdir}/kram/kram-qt
fi

%post gtk
[ -L %{_bindir}/kram ] || rm -f %{_bindir}/kram
%{_sbindir}/alternatives --install %{_bindir}/kram kram %{_libexecdir}/kram/kram-gtk 10

%postun gtk
if [ $1 -eq 0 ]; then
    %{_sbindir}/alternatives --remove kram %{_libexecdir}/kram/kram-gtk
fi

%posttrans common
state=%{_localstatedir}/lib/rpm-state/kram/enabled-units
if [ -s "$state" ]; then
    for user in $(cut -d' ' -f1 "$state" | sort -u); do
        units=$(sed -n "s/^$user //p" "$state")
        SYSTEMD_BUS_TIMEOUT=15s systemctl --user -M "$user@" enable --now $units >/dev/null 2>&1 || :
        # as Kram's settings do: count now, which shows the tray icon when there are updates
        SYSTEMD_BUS_TIMEOUT=15s systemctl --user -M "$user@" start --no-block kram-update-check.service >/dev/null 2>&1 || :
    done
fi
rm -f "$state"
:

%files common -f %{name}.lang
%doc README.md
%license LICENSE
%{python3_sitelib}/kram/
%exclude %{python3_sitelib}/kram/qt/
%exclude %{python3_sitelib}/kram/gtk/
%{python3_sitelib}/kram-*.dist-info/
%dir %attr(0700,root,root) %{_localstatedir}/cache/kram
%dir %attr(0700,root,root) %{_localstatedir}/lib/rpm-state/kram
%{_libexecdir}/kram-helper
%dir %{_libexecdir}/kram
%{_datadir}/polkit-1/actions/%{appid}.policy
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
%{_userunitdir}/kram-update-check.service
%{_userunitdir}/kram-update-check.timer
%{_userunitdir}/kram-update-check.path
%{_userunitdir}/kram-tray.service
%{_datadir}/icons/hicolor/scalable/status/%{appid}-update-*.svg
%{_datadir}/kram/

%files qt
%{gui_files}
# A software centre installs an AppStream component through the package that holds its metainfo: kram-qt, as
# "dnf install kram" does. Not in kram-gtk too: appstream-builder keeps one of two packages with the same component
# (it kept kram-gtk) and vetoes the other as a duplicate. kram-gtk is installed with dnf (README).
%{_metainfodir}/%{appid}.metainfo.xml
%ghost %{_bindir}/kram
%{_libexecdir}/kram/kram-qt
%{python3_sitelib}/kram/qt/

%files gtk
%{gui_files}
%ghost %{_bindir}/kram
%{_libexecdir}/kram/kram-gtk
%{python3_sitelib}/kram/gtk/

%changelog
* Wed Nov 25 2026 Modo Ltunzher <offnormal@gmail.com> - 0.14.2-1
- Packages replaced by a package of another name (Obsoletes), such as kram by kram-qt, are upgradable again
- GTK front end: the Mark All Upgrades and COPR buttons have icons with the Breeze icon theme

* Mon Nov 23 2026 Modo Ltunzher <offnormal@gmail.com> - 0.14.1-1
- COPR: the search no longer offers to enable a project that is already enabled
- GTK front end: right-clicking a selected package that is not installed opens the context menu again

* Mon Nov 23 2026 Modo Ltunzher <offnormal@gmail.com> - 0.14.0-1
- GTK front end: the button for a new Fedora release sits in the left half of the header bar
- Repositories: Mirrors… lists a repository's mirrors, tests how fast each one is and pins the repository to the one you choose, or back to automatic
- Repositories: a switch for dnf's own fastest-mirror search
- Repositories: a Mirror column shows which mirror each repository uses
- Repositories: the window stays open while you remove a repository or choose a mirror, and shows the result
- Mirrors: choosing a mirror keeps the window open and shows the mirror in use once it is applied
- About: What's New opens over About instead of replacing it
- Qt front end: the section buttons under the filter list have icons
- GTK front end: the Repositories and COPR buttons sit in the left half of the header bar, as in the Qt toolbar
- Packaging: the Kram packages name their packager

* Sun Nov 22 2026 Modo Ltunzher <offnormal@gmail.com> - 0.13.0-1
- Applying changes: when a marked package conflicts with installed ones, Kram offers to mark those for removal, as dnf swap does (kram-qt for kram-gtk, ffmpeg-free for ffmpeg)
- Applying changes: the equivalent command of several kinds of change is one dnf5 do, a single transaction as Kram runs it

* Sun Nov 22 2026 Modo Ltunzher <offnormal@gmail.com> - 0.12.1-1
- Fedora Rawhide: the packages build again (the test run crashed on exit)
- Packaging: installing kram-gtk over Kram 0.11 explains the conflict instead of failing in rpm; use dnf swap kram kram-gtk

* Sun Nov 22 2026 Modo Ltunzher <offnormal@gmail.com> - 0.12.0-1
- GNOME: a GTK 4 and libadwaita front end, kram-gtk, with the package list, menus, preferences and every dialog of the Qt one
- Switching front ends: dnf swap kram-qt kram-gtk, and back; the settings and the tray icon stay as they are
- Packaging: kram is now kram-qt and kram-common; dnf upgrade replaces the old package and keeps the tray icon on
- About: shows which front end and toolkit version is running
- Icons: the painted status and origin icons are sharp at fractional screen scales (125 %, 150 %)

* Sat Nov 21 2026 Modo Ltunzher <offnormal@gmail.com> - 0.11.3-1
- GNOME: Kram turns light or dark along with the desktop, in libadwaita's colours

* Fri Nov 20 2026 Modo Ltunzher <offnormal@gmail.com> - 0.11.2-1
- Apply works again (in 0.11.1 it did nothing)

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
