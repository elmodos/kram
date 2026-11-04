# Publishing Kram in COPR

The project exists: https://copr.fedorainfracloud.org/coprs/elmodos/Kram/ (note the capital K in the project
name). It builds `packaging/kram.spec` through `.copr/Makefile` (COPR's *make srpm* build method).
The steps below are how it was set up, for reference or for a new project.

## 1. Create the project

1. Log in at https://copr.fedorainfracloud.org (Fedora account, FAS).
2. **New Project**:
   - Name: `Kram`
   - Description / instructions: "Synaptic-style package manager for Fedora (dnf5)", link to
     https://github.com/elmodos/kram
   - Chroots: `fedora-44-x86_64`, `fedora-rawhide-x86_64` (and `fedora-43-x86_64` if wanted).
     The package is `noarch`, so one architecture per release is enough; add `aarch64` only if you want it listed.
   - Leave "Follow Fedora branching" on, so new releases get a chroot automatically.

## 2. Add the package

Project → **Packages** → **New package** → source type **SCM**:

| Field | Value |
|---|---|
| Package name | `kram` |
| Clone URL | `https://github.com/elmodos/kram.git` |
| Committish | the latest release tag, e.g. `v0.1.0` (or `main` for snapshot builds) |
| Subdirectory | empty |
| Spec file | `packaging/kram.spec` |
| Type | Git |
| SRPM build method | **make srpm** |
| Auto-rebuild | off for release builds; ✓ only for a snapshot project with the webhook below |

Save, then **Rebuild** to run the first build. The SRPM step runs `.copr/Makefile`: it archives the commit. The
commit tagged `v<version>` builds as a plain release (`kram-0.1.0-2`); any other commit gets a snapshot version
`0.1.0^YYYYMMDDgit<hash>`, which sorts after the release it follows and before the next one.
`%check` runs desktop-file-validate, appstream-util and the test suite; a failing test fails the build.

## 3. Rebuild on every push (optional, for a separate snapshot project)

Every push to `main` would publish a snapshot (`0.1.0^…git…`) in place of the release, so do this only in a
second project (e.g. `elmodos/Kram-nightly`, Committish `main`, Auto-rebuild on), not in `elmodos/Kram`.

1. In Copr: project → **Settings** → **Integrations** → copy the GitHub webhook URL.
2. On GitHub: repository → **Settings** → **Webhooks** → **Add webhook**:
   payload URL = that URL, content type `application/json`, "Just the push event".

Pushes to `main` then start a build automatically.

## 4. Install from COPR

```sh
sudo dnf copr enable elmodos/Kram
sudo dnf install kram
```

## Releases

1. Bump the version in `pyproject.toml`, `kram/__init__.py`, `%global base_version` in `packaging/kram.spec`
   (reset `Release:` to 1, add a `%changelog` entry) and add a `<release>` to
   `data/io.github.elmodos.Kram.metainfo.xml`. `tests/test_packaging.py` fails if they disagree.
2. Commit, `git tag -a v<version> -m "Kram <version>"`, `git push origin main v<version>`.
3. In Copr: package `kram` → Edit → Committish `v<version>` → Save → Rebuild.

`0.1.0` was released as `0.1.0-2`: the snapshot builds made before tagging were `0.1.0-1.YYYYMMDDgit<hash>`,
which rpm sorts after `0.1.0-1`.

## Before pushing a packaging change

```sh
scripts/rpm_check.sh 44 /tmp/kram-rpms   # same SRPM → RPM steps as COPR, in a container; RPMs copied out
```

It builds, installs the RPM in a clean Fedora container and checks the helper, the polkit policy and the
translations. The first run downloads the build dependencies (a few minutes); they are cached in the podman volume
`kram-dnf-cache-44`.

## Notes

- The metainfo screenshots point at `docs/screenshots/*.png` on `main` (raw.githubusercontent.com); replace the
  images to change them, the URLs stay the same. They are real screenshots taken on Plasma.
- Runtime dependencies: python3-libdnf5, python3-rpm, python3-pyside6, polkit, dnf5-plugins (for `dnf5 copr`
  and `dnf5 config-manager`).
