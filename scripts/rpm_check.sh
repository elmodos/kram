#!/bin/bash
# Build the RPM the way COPR does (.copr/Makefile → SRPM → rpmbuild) in a throwaway Fedora container, install
# it and check the installed layout. Uncommitted changes are included.
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
    echo "### build (with %check: desktop-file-validate, appstream-util, pytest)"
    dnf5 -q -y builddep "$srpm" >/dev/null 2>&1
    # %generate_buildrequires: let rpmbuild list the dynamic BuildRequires, install them, then build
    rpmbuild -rr "$srpm" --define "_srcrpmdir /out/br" >/dev/null 2>&1 || true
    dnf5 -q -y builddep /out/br/*.buildreqs.nosrc.rpm >/dev/null 2>&1
    if ! rpmbuild --rebuild "$srpm" --define "_rpmdir /out" >/tmp/build.log 2>&1; then
        tail -60 /tmp/build.log; exit 1
    fi
    grep -E "^(warning|E:|W:)|passed|failed|validated" /tmp/build.log || true
    rpm=$(ls /out/noarch/kram-*.noarch.rpm) && echo "$rpm"
    echo "### install"
    rm -f /etc/rpm/macros.image-language-conf  # the container image skips translations (%_install_langs)
    dnf5 -q -y install "$rpm" >/dev/null 2>&1
    rpm -ql kram | grep -v "site-packages/kram/.*\.py$\|__pycache__"
    head -1 /usr/libexec/kram-helper
    echo "### installed helper (as root)"
    printf "%s\n" "{\"op\":\"ping\"}" "{\"op\":\"quit\"}" | /usr/libexec/kram-helper | head -1
    echo "### the GUI uses the installed helper and translations"
    cd /  # not /build: that is a source checkout, and python3 -c would import kram from it
    QT_QPA_PLATFORM=offscreen LANGUAGE=uk python3 -c "
from kram.ipc.client import HelperClient, _installed
from kram.i18n import _
import kram
assert _installed(), kram.__file__
print(kram.__file__, HelperClient()._command(), _(\"Reload\"))
"
    xmllint --noout --dtdvalid /usr/share/polkit-1/policyconfig-1.dtd /usr/share/polkit-1/actions/io.github.elmodos.Kram.policy 2>/dev/null \
        && echo "policy: valid" || echo "policy: xmllint/dtd not available, skipped"
    echo "ALL CHECKS PASSED"
'
