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
| Auto-rebuild | ✓ (lets the tag webhook below start builds) |

Save, then **Rebuild** to run the first build. The SRPM step runs `.copr/Makefile`: it archives the commit. The
commit tagged `v<version>` builds as a plain release (`kram-0.1.0-2`); any other commit gets a snapshot version
`0.1.0^YYYYMMDDgit<hash>`, which sorts after the release it follows and before the next one.
`%check` runs desktop-file-validate, appstream-util and the test suite; a failing test fails the build.

## 3. Build automatically when a release tag is pushed

1. In Copr: project → **Settings** → **Integrations** → copy the GitHub webhook URL
   (`https://copr.fedorainfracloud.org/webhooks/github/<id>/<secret>/`) and append the package name: `…/kram/`.
2. On GitHub: repository → **Settings** → **Webhooks** → **Add webhook**: that payload URL, content type
   `application/json`, "Let me select individual events" → only **Branch or tag creation**.
   (Or: `gh api repos/elmodos/kram/hooks -f name=web -f 'config[url]=<URL>' -f 'config[content_type]=json'
   -f 'events[]=create'`.)

How Copr handles it (frontend `webhooks_general.py`, `packages_logic.py`):
- A tag creation event builds the package named in the URL, with the tag as the committish, so
  `.copr/Makefile` sees the tagged commit and builds a plain release.
- Without the package name in the URL, a tag only matches a package if it looks like `kram-<version>`; our tags
  are `v<version>`, hence `…/kram/`.
- Branch pushes are not sent (no push event), and would not match anyway: Copr rebuilds on a branch push only
  when the package's Committish ends with that branch, and ours is a tag.

For snapshots of every push to `main`, use a second project (e.g. `elmodos/Kram-nightly`, Committish `main`,
Auto-rebuild on, webhook with the **push** event); never in `elmodos/Kram`, where a snapshot would replace the
release.

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
3. The tag webhook (section 3) starts the Copr build. Optionally set the package's Committish to the new tag
   too, so a manual **Rebuild** in Copr builds the latest release rather than the previous one.

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

- README badges: the build status and version come from Copr and update themselves; the "Fedora 43 | 44 | 45 |
  Rawhide" badge is static (shields.io can't list the project's chroots), so edit it when the chroots change.

- The metainfo screenshots point at `docs/screenshots/*.png` on `main` (raw.githubusercontent.com); replace the
  images to change them, the URLs stay the same. They are real screenshots taken on Plasma.
- Runtime dependencies: python3-libdnf5, python3-rpm, python3-pyside6, polkit, dnf5-plugins (for `dnf5 copr`
  and `dnf5 config-manager`).
