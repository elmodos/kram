# Kram in COPR

The project exists: https://copr.fedorainfracloud.org/coprs/elmodos/Kram/ (note the capital K in the project
name). It builds `packaging/kram.spec` through `.copr/Makefile` (COPR's *make srpm* build method), for every
Fedora chroot Copr offers; the package is `noarch`. Users install it with:

```sh
sudo dnf copr enable elmodos/Kram
sudo dnf install kram
```

## How a build starts

The package is an SCM source (`https://github.com/elmodos/kram.git`, spec `packaging/kram.spec`, SRPM build
method **make srpm**, auto-rebuild on). The SRPM step runs `.copr/Makefile`: it archives the commit. The commit
tagged `v<version>` builds as a plain release (`kram-0.4.0-1`); any other commit gets a snapshot version
`0.4.0^YYYYMMDDgit<hash>`, which sorts after the release it follows and before the next one. `%check` runs
desktop-file-validate, appstream-util and the test suite; a failing test fails the build.

Pushing a tag starts the build through a GitHub webhook (repository → Settings → Webhooks, only the **Branch or
tag creation** event) whose payload URL is the project's webhook URL from Copr (project → Settings →
Integrations) with the package name appended: `https://copr.fedorainfracloud.org/webhooks/github/<id>/<secret>/kram/`.
How Copr treats it:

- A tag creation event builds the package named in the URL, with the tag as the committish, so
  `.copr/Makefile` sees the tagged commit and builds a plain release.
- Without the package name in the URL, a tag only matches a package named like `kram-<version>`; our tags are
  `v<version>`, hence the trailing `/kram/`.
- Branch pushes are not sent, and would not match anyway: Copr rebuilds on a branch push only when the package's
  Committish ends with that branch, and ours is a tag.

For snapshots of every push to `main`, use a second project (e.g. `elmodos/Kram-nightly`, Committish `main`,
webhook with the **push** event), never `elmodos/Kram`, where a snapshot would replace the release.

## Releases

1. Bump the version in `pyproject.toml`, `kram/__init__.py`, `%global base_version` in `packaging/kram.spec`
   (reset `Release:` to 1, add a `%changelog` entry) and add a `<release>` to
   `data/io.github.elmodos.Kram.metainfo.xml`. `tests/test_packaging.py` fails if they disagree.
2. Commit "Release X.Y.Z", `git tag -a v<version> -m "Kram <version>"`, run `scripts/rpm_check.sh` (below),
   then `git push origin main v<version>`.
3. The tag webhook starts the Copr build.

## Before pushing a packaging change or a release

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
