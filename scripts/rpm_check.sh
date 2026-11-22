#!/bin/bash
# Build the RPMs the way COPR does (.copr/Makefile → SRPM → rpmbuild) in a throwaway Fedora container, install
# them and check the installed layout: kram-common with kram-qt first, then kram-gtk in place of kram-qt.
# Uncommitted changes are included.
# Usage: scripts/rpm_check.sh [release, default 44] [directory to copy the built SRPM and RPM to]
set -euo pipefail
release=${1:-44}
src=$(cd "$(dirname "$0")/.." && pwd)
out=()
if [ -n "${2:-}" ]; then
    mkdir -p "$2"
    out=(-v "$(cd "$2" && pwd):/out:Z")
fi
# downloaded packages are kept in a podman volume between runs (podman volume rm kram-dnf-cache-<release>)
exec podman run --rm "${out[@]}" -v "$src:/src:ro,Z" -v "kram-dnf-cache-$release:/var/cache/libdnf5:Z" \
        "registry.fedoraproject.org/fedora:$release" bash -euo pipefail -c '
    echo keepcache=True >> /etc/dnf/dnf.conf
    dnf5 -q -y install rpm-build make git-core "dnf5-command(builddep)" libxml2 >/dev/null 2>&1
    cp -a /src /build && cd /build
    git config --global user.email check@localhost && git config --global user.name check
    if [ -n "$(git status --porcelain)" ]; then git add -A && git commit -qm "uncommitted changes"; fi
    echo "### SRPM"
    make -s -f .copr/Makefile srpm outdir=/out
    srpm=$(ls /out/*.src.rpm) && echo "$srpm"
    echo "### build (with %check: desktop-file-validate, appstream-util, pytest incl. the GTK tests)"
    dnf5 -q -y builddep "$srpm" >/dev/null 2>&1
    # %generate_buildrequires: let rpmbuild list the dynamic BuildRequires, install them, then build
    rpmbuild -rr "$srpm" --define "_srcrpmdir /out/br" >/dev/null 2>&1 || true
    dnf5 -q -y builddep /out/br/*.buildreqs.nosrc.rpm >/dev/null 2>&1
    if ! rpmbuild --rebuild "$srpm" --define "_rpmdir /out" >/tmp/build.log 2>&1; then
        tail -60 /tmp/build.log; exit 1
    fi
    grep -E "^(warning|E:|W:)|passed|failed|validated" /tmp/build.log || true
    ls /out/noarch/kram-*.noarch.rpm
    common=$(ls /out/noarch/kram-common-*.noarch.rpm)
    echo "### install kram-common and kram-qt"
    rm -f /etc/rpm/macros.image-language-conf  # the container image skips translations (%_install_langs)
    # a local repository, so that dnf resolves kram, kram-qt and kram-gtk by name
    dnf5 -q -y install createrepo_c >/dev/null 2>&1
    mkdir /repo && cp /out/noarch/kram-*.noarch.rpm /repo/ && createrepo_c -q /repo
    printf "[kram-local]\nname=kram local\nbaseurl=file:///repo\ngpgcheck=0\n" > /etc/yum.repos.d/kram-local.repo
    dnf5 -q -y install kram >/dev/null 2>&1  # kram-qt provides kram
    rpm -qa "kram*" | sort
    rpm -ql kram-common kram-qt | grep -v "site-packages/kram/.*\.py$\|__pycache__"
    head -1 /usr/libexec/kram-helper
    launcher() {  # $1 = qt or gtk: /usr/bin/kram is the alternatives link to its launcher
        [ "$(readlink -f /usr/bin/kram)" = "/usr/libexec/kram/kram-$1" ] || { ls -l /usr/bin/kram; exit 1; }
        echo "/usr/bin/kram → $(readlink -f /usr/bin/kram): $(grep -m1 "^from kram" /usr/bin/kram)"
    }
    launcher qt
    python3 -c "import kram.qt.__main__"
    echo "### installed helper (as root)"
    printf "%s\n" "{\"op\":\"ping\"}" "{\"op\":\"quit\"}" | /usr/libexec/kram-helper | head -1
    echo "### local_install (as root, files of a normal user)"
    dnf5 -q download --destdir /tmp/dl hello >/dev/null 2>&1
    python3 /build/scripts/check_local_install.py "$common" /tmp/dl/hello-*.rpm
    echo "### the installer: upgrade, downgrade, kernel-like, newer in a repository (test packages)"
    (cd / && python3 /build/scripts/check_local_versions.py)
    echo "### the GUI uses the installed helper and translations"
    cd /  # not /build: that is a source checkout, and python3 -c would import kram from it
    QT_QPA_PLATFORM=offscreen LANGUAGE=uk python3 -c "
from kram.ipc.client import HelperClient, _installed
from kram.i18n import _
import kram
assert _installed(), kram.__file__
from kram.core import releases
assert releases.load()[0].version == kram.__version__  # the release notes come from the installed metainfo
print(kram.__file__, HelperClient(lambda _f: None)._command(), _(\"Reload\"))
"
    xmllint --noout --dtdvalid /usr/share/polkit-1/policyconfig-1.dtd /usr/share/polkit-1/actions/io.github.elmodos.Kram.policy 2>/dev/null \
        && echo "policy: valid" || echo "policy: xmllint/dtd not available, skipped"
    echo "### kram-gtk in place of kram-qt"
    dnf5 -q -y swap kram-qt kram-gtk >/dev/null 2>&1
    rpm -qa "kram*" | sort
    launcher gtk
    python3 -c "import kram.gtk.app"
    # software centres install kram-qt: only it has the AppStream metainfo; What is New reads the copy in kram-common
    if [ -e /usr/share/metainfo/io.github.elmodos.Kram.metainfo.xml ]; then echo "kram-gtk has AppStream metainfo"; exit 1; fi
    python3 -c "
import kram
from kram.core import releases
assert releases.load()[0].version == kram.__version__
print(\"release notes without kram-qt:\", releases.load()[0].version)
"
    echo "### what each front end pulls in"
    deps() { dnf5 -q repoquery --requires --resolve --recursive "$1" 2>/dev/null; }
    if deps kram-gtk | grep -iE "pyside|qt6-qtbase"; then echo "kram-gtk pulls in Qt"; exit 1; fi
    if deps kram-qt | grep -E "^(gtk4|libadwaita)-[0-9]"; then echo "kram-qt pulls in GTK 4"; exit 1; fi
    echo "kram-gtk: no Qt; kram-qt: no GTK 4 / libadwaita"
    echo "ALL CHECKS PASSED"
'
