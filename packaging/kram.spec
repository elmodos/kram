%global appid io.github.elmodos.Kram

Name:           kram
Version:        0.1.0
# .copr/Makefile defines "snapshot" (.YYYYMMDDgitHASH) for builds from git
Release:        1%{?snapshot}%{?dist}
Summary:        Synaptic-style package manager for Fedora

License:        GPL-3.0-or-later
URL:            https://github.com/elmodos/kram
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  gettext
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
# for the test suite
BuildRequires:  python3-pytest
BuildRequires:  python3-libdnf5
BuildRequires:  python3-rpm

Requires:       python3-libdnf5
Requires:       python3-rpm
Requires:       python3-pyside6
Requires:       polkit
# "dnf5 copr" and "dnf5 config-manager" (COPR and repository changes)
Requires:       dnf5-plugins
Requires:       hicolor-icon-theme

%description
Kram is a package manager in the style of Synaptic, built on libdnf5. It lists every package in the enabled
repositories with its status, origin (Fedora, COPR, third-party), versions and size; has ranked search by
name, description, provides and files; marks changes, previews the whole transaction and applies it. It also
enables and disables repositories and manages COPR projects.

%prep
%autosetup -n %{name}-%{version}

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
mkdir -p %{buildroot}%{_datadir}/locale
cp -a build-locale/. %{buildroot}%{_datadir}/locale/
%find_lang %{name}

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{appid}.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/%{appid}.metainfo.xml
%pytest

%files -f %{pyproject_files} -f %{name}.lang
%doc README.md
%{_bindir}/kram
%{_libexecdir}/kram-helper
%{_datadir}/polkit-1/actions/%{appid}.policy
%{_datadir}/applications/%{appid}.desktop
%{_metainfodir}/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg

%changelog
* Tue Nov 03 2026 Modo Ltunzher <offnormal@gmail.com> - 0.1.0-1
- First release
