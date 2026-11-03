#!/bin/bash
# Translation maintenance (gettext). Source strings are English, in the Python code.
#   scripts/i18n.sh pot          extract strings into po/kram.pot
#   scripts/i18n.sh update       pot + merge it into every po/*.po
#   scripts/i18n.sh new LANG     start po/LANG.po from the template
#   scripts/i18n.sh check        compile every po/*.po with checks (no output files)
# Running from a checkout compiles po/*.po into kram/locale automatically (see kram/i18n.py).
set -euo pipefail
cd "$(dirname "$0")/.."

pot() {
    find kram -name '*.py' -not -path '*/helper/*' | sort | xargs xgettext \
        --language=Python --from-code=UTF-8 --add-comments=TRANSLATORS \
        --keyword=_ --keyword=N_ --keyword=ngettext:1,2 --keyword=pgettext:1c,2 \
        --package-name=kram --msgid-bugs-address=https://github.com/elmodos/kram/issues \
        --sort-by-file -o po/kram.pot
    echo "po/kram.pot: $(grep -c '^msgid ' po/kram.pot) strings"
}

case "${1:-}" in
    pot) pot ;;
    update)
        pot
        for po in po/*.po; do
            msgmerge --quiet --update --backup=none --previous "$po" po/kram.pot
            echo "$po: $(msgfmt --statistics -o /dev/null "$po" 2>&1)"
        done ;;
    new)
        lang=${2:?usage: $0 new LANG}
        pot
        msginit --no-translator --locale="$lang" --input=po/kram.pot --output-file="po/$lang.po" ;;
    check)
        for po in po/*.po; do
            echo -n "$po: "
            msgfmt --check --statistics -o /dev/null "$po"
        done ;;
    *) sed -n '2,7p' "$0"; exit 2 ;;
esac
