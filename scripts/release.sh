#!/bin/bash
# Prepare a Kram release locally: bump the version everywhere, write the %changelog entry and the metainfo
# <release> from the `Changelog:` trailers of the commits since the last tag, commit "Release X.Y.Z", tag it and
# run scripts/rpm_check.sh. Nothing is pushed: pushing the tag publishes the release (Copr build + GitHub release).
#
# Usage: scripts/release.sh X.Y.Z [--no-edit] [--no-check]   (without X.Y.Z: show the last release)
#   --no-edit   take the changelog items from the trailers as they are (no editor)
#   --no-check  skip scripts/rpm_check.sh
#
# The items open in $GIT_EDITOR first, one "- item" per line; an empty file aborts. Undo a release that was not
# pushed yet with: git tag -d vX.Y.Z && git reset --hard HEAD~1
set -euo pipefail

usage() { sed -n '6,9p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

version="" edit=1 check=1
for arg in "$@"; do
    case $arg in
        --no-edit) edit=0 ;;
        --no-check) check=0 ;;
        -h|--help) usage ;;
        -*) echo "unknown option: $arg" >&2; usage ;;
        *) [ -z "$version" ] || usage; version=$arg ;;
    esac
done
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

previous=$(git describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || true)
if [ -n "$previous" ]; then
    echo "Last release: $previous ($(git log -1 --format=%cs "$previous"), $(git rev-list --count "$previous"..HEAD) commits since)"
else
    echo "Last release: none"
fi

[ -n "$version" ] || usage
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "the version must be X.Y.Z, not $version" >&2; exit 2; }
tag=v$version

die() { echo "release.sh: $*" >&2; exit 1; }
[ "$(git branch --show-current)" = main ] || die "release from main (now on $(git branch --show-current))"
[ -z "$(git status --porcelain)" ] || die "the working tree has uncommitted changes"
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && die "tag $tag already exists"

current=$(sed -n 's/^%global base_version[[:space:]]*//p' packaging/kram.spec)
[ "$(printf '%s\n%s\n' "$current" "$version" | sort -V | tail -1)" = "$version" ] && [ "$current" != "$version" ] \
    || die "$version is not newer than the current $current"

range=${previous:+$previous..}HEAD
items=$(mktemp --suffix=.kram-changelog)
trap 'rm -f "$items"' EXIT
{
    echo "# Kram $version: changelog items since ${previous:-the first commit}, one \"- item\" per line."
    echo "# They go to packaging/kram.spec as they are and to the metainfo as sentences. Lines with # are dropped;"
    echo "# leave no item to abort."
    git log --reverse --format='%(trailers:key=Changelog,valueonly,unfold)' "$range" | sed '/^[[:space:]]*$/d; s/^/- /'
} >"$items"

if [ "$edit" = 1 ]; then
    "$(git var GIT_EDITOR)" "$items" </dev/tty >/dev/tty
fi
sed -i '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$items"
[ -s "$items" ] || die "no changelog items (commits since ${previous:-the start} have no Changelog: trailers)"
grep -qv '^- ' "$items" && die "every item must start with \"- \":"$'\n'"$(grep -v '^- ' "$items")"

packager="$(git config user.name) <$(git config user.email)>"
python3 -I - "$root" "$version" "$items" "$packager" <<'EOF'
import datetime
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

root, version, items_file, packager = Path(sys.argv[1]), *sys.argv[2:]
items = [line[2:].strip() for line in Path(items_file).read_text().splitlines()]
today = datetime.date.today()


def sub(path, pattern, repl, flags=re.MULTILINE):
    path = root / path
    text, n = re.subn(pattern, repl, path.read_text(), count=1, flags=flags)
    if n != 1:
        sys.exit(f"release.sh: {path.relative_to(root)}: no match for {pattern!r}")
    path.write_text(text)


sub("pyproject.toml", r'^version = "[^"]*"', f'version = "{version}"')
sub("kram/__init__.py", r'^__version__ = "[^"]*"', f'__version__ = "{version}"')
sub("packaging/kram.spec", r"^(%global base_version\s+)\S+", rf"\g<1>{version}")
sub("packaging/kram.spec", r"^(Release:\s+)\d+", r"\g<1>1")
# rpm wants the C locale's day and month names
day = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[today.weekday()]
month = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")[today.month - 1]
entry = f"* {day} {month} {today.day:02d} {today.year} {packager} - {version}-1\n"
entry += "".join(f"- {item}\n" for item in items)
sub("packaging/kram.spec", r"^%changelog\n", lambda m: m.group(0) + entry + "\n")


def sentence(item):
    item = item[0].upper() + item[1:]
    return item if item.endswith((".", "!", "?")) else item + "."


lis = "".join(f"          <li>{escape(sentence(item))}</li>\n" for item in items)
release = (f'    <release version="{version}" date="{today.isoformat()}">\n'
           "      <description>\n        <ul>\n" + lis + "        </ul>\n      </description>\n    </release>\n")
sub("data/io.github.elmodos.Kram.metainfo.xml", r"^  <releases>\n", lambda m: m.group(0) + release)
EOF

git add pyproject.toml kram/__init__.py packaging/kram.spec data/io.github.elmodos.Kram.metainfo.xml
git commit -q -m "Release $version"
git tag -a "$tag" -m "Kram $version"
echo "### committed \"Release $version\" and tagged $tag"
git show --stat --format='%h %s' HEAD | sed 's/^/  /'

if [ "$check" = 1 ]; then
    out=$(mktemp -d --tmpdir "kram-$version-rpms.XXXX")
    echo "### scripts/rpm_check.sh 44 $out"
    if ! scripts/rpm_check.sh 44 "$out"; then
        echo "rpm_check.sh failed; to undo: git tag -d $tag && git reset --hard HEAD~1" >&2
        exit 1
    fi
fi

cat <<MSG

Ready. Publish (Copr build and GitHub release) with:
  git push origin main $tag
Undo instead: git tag -d $tag && git reset --hard HEAD~1
MSG
