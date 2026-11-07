"""Run by scripts/rpm_check.sh as root inside the container, after check_local_install.py (which creates the user).

Builds empty test packages and walks the installer's cases through the installed catalog and helper: install,
upgrade, downgrade, a kernel-like package installed next to the old version, a newer version in a repository,
an unsatisfiable requirement, a foreign architecture, and forget_local.
"""
import os
import subprocess
import sys
from pathlib import Path

from check_local_install import expect, helper, sha256

import libdnf5
from kram.core.catalog import Catalog

WORK = Path("/tmp/kramtest")
SPEC = """Name: {name}
Version: {version}
Release: 1
Summary: Kram test package
License: MIT
{extra}
%description
A package for Kram's installer checks.
%files
"""


def build(name: str, version: str, extra: str = "BuildArch: noarch", target: str = "") -> str:
    spec = WORK / f"{name}-{version}.spec"
    spec.write_text(SPEC.format(name=name, version=version, extra=extra))
    out = WORK / "rpms"
    cmd = ["rpmbuild", "-bb", "--quiet", "--define", f"_rpmdir {out}", "--define", "_build_id_links none", str(spec)]
    if target:
        cmd[1:1] = ["--target", target]
    subprocess.run(cmd, check=True, capture_output=True)
    found = sorted(out.rglob(f"{name}-{version}-1.*.rpm"))
    path = found[-1]
    path.chmod(0o644)
    return str(path)


def check(name: str, good: bool, detail: object = "") -> None:
    print(("ok   " if good else "FAIL ") + name + ("" if good else f": {detail}"))
    if not good:
        sys.exit(1)


def installed(name: str) -> list[str]:
    out = subprocess.run(["rpm", "-q", "--qf", "%{VERSION}\n", name], capture_output=True, text=True)
    return sorted(out.stdout.split()) if out.returncode == 0 else []


def target(path: str):
    catalog = Catalog()
    catalog.load()
    return catalog, catalog.open_local(path)


def install(path: str, action: str) -> None:
    expect(f"local_install {os.path.basename(path)} ({action})", helper(path=path, sha256=sha256(path), action=action),
           True)


def main() -> None:
    WORK.mkdir(mode=0o755)
    v1, v2, v3 = (build("kramtest", v, "BuildArch: noarch\nRequires: bash") for v in ("1.0", "2.0", "3.0"))
    k1, k2 = (build("kramtest-kernel", v, "BuildArch: noarch\nProvides: installonlypkg(kernel)") for v in ("1.0", "2.0"))
    broken = build("kramtest-broken", "1.0", "BuildArch: noarch\nRequires: kramtest-no-such-thing")
    foreign = build("kramtest-foreign", "1.0", "", target="aarch64")

    catalog, t = target(v1)
    check("not installed: install", t.action == "install", t)
    reqs = {r.text: r for r in t.deps["requires"]}
    check("bash is required and installed", reqs["bash"].installed == ["bash"], reqs)
    install(v1, t.helper_action)
    check("1.0 installed", installed("kramtest") == ["1.0"], installed("kramtest"))

    catalog, t = target(v2)
    check("newer file: upgrade", (t.action, t.installed_evr, t.helper_action) == ("upgrade", "1.0-1", "install"), t)
    install(v2, t.helper_action)
    check("upgraded to 2.0", installed("kramtest") == ["2.0"], installed("kramtest"))

    catalog, t = target(v1)
    check("older file: downgrade", (t.action, t.installed_evr) == ("downgrade", "2.0-1"), t)
    install(v1, t.helper_action)
    check("downgraded to 1.0", installed("kramtest") == ["1.0"], installed("kramtest"))

    catalog, t = target(v1)
    check("the same version: reinstall", t.action == "reinstall", t)

    catalog, t = target(k1)
    install(k1, t.helper_action)
    catalog, t = target(k2)
    check("kernel-like newer file: next to the old one",
          (t.action, t.installed_evr, t.helper_action) == ("alongside", "1.0-1", "install"), t)
    install(k2, t.helper_action)
    check("both kernel-like versions installed", installed("kramtest-kernel") == ["1.0", "2.0"],
          installed("kramtest-kernel"))

    catalog, t = target(broken)
    preview = catalog.resolve_local(broken, t.helper_action, [])
    missing = t.deps["requires"][0]
    check("an unsatisfiable requirement: not installable, nothing provides it",
          not preview.ok and not missing.installed and not missing.available and not missing.own, (preview, missing))
    catalog, t = target(foreign)
    preview = catalog.resolve_local(foreign, t.helper_action, [])
    check("another architecture: not installable", not preview.ok, preview)
    print("     " + preview.problems[0].replace("\n", "\n     "))

    # another package operation running: rpm's transaction lock is held, as dnf5 or PackageKit would hold it
    holder = subprocess.Popen([sys.executable, "-c", (
        "import fcntl, os, sys, time\n"
        "os.makedirs('/run/dnf', exist_ok=True)\n"
        "fd = os.open('/run/dnf/rpmtransaction.lock', os.O_RDWR | os.O_CREAT, 0o644)\n"
        "fcntl.lockf(fd, fcntl.LOCK_EX)\n"
        "print('locked', flush=True)\n"
        "time.sleep(60)")], stdout=subprocess.PIPE, text=True)
    holder.stdout.readline()
    done = helper(path=v2, sha256=sha256(v2), action="install")
    holder.kill()
    holder.wait()
    check("another package operation running: a plain error, nothing installed",
          done.get("stage") == "locked" and f"(pid {holder.pid})" in done.get("process", "")
          and installed("kramtest") == ["1.0"], done)

    repo = WORK / "repo"
    repo.mkdir()
    os.link(v3, repo / os.path.basename(v3))
    subprocess.run(["createrepo_c", "-q", str(repo)], check=True)
    Path("/etc/yum.repos.d/kramtest.repo").write_text(
        f"[kramtest]\nname=Kram test\nbaseurl=file://{repo}\ngpgcheck=0\n")
    subprocess.run(["dnf5", "-q", "makecache"], check=True)
    catalog, t = target(v2)
    check("a newer version in a repository", (t.repo_newer, t.repo_evr, t.repo_id) == (True, "3.0-1", "kramtest"), t)
    catalog.forget_local()
    q = libdnf5.rpm.PackageQuery(catalog._base)
    q.filter_name(["kramtest"])
    q.filter_available()
    check("after forget_local the file is no candidate", sorted(p.get_repo_id() for p in q) == ["kramtest"],
          [(p.get_nevra(), p.get_repo_id()) for p in q])
    preview = catalog.resolve({"op": "transaction", "upgrade": ["kramtest"]})
    check("an upgrade mark takes the repository's version",
          [(i.evr, i.repo_id) for i in preview.items if i.action == "upgrade"] == [("3.0-1", "kramtest")], preview)
    print("LOCAL VERSION CHECKS PASSED")


if __name__ == "__main__":
    main()
