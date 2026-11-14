# Translating Kram

Kram follows the desktop's language setting. To try a language without changing the desktop:
`LANGUAGE=de python3 -m kram`.

| Language | | Code | Status |
|---|---|---|---|
| Čeština | Czech | `cs` | needs review |
| Deutsch | German | `de` | needs review |
| English | English | — | source |
| Español | Spanish | `es` | needs review |
| Français | French | `fr` | needs review |
| Italiano | Italian | `it` | needs review |
| 日本語 | Japanese | `ja` | needs review |
| 한국어 | Korean | `ko` | needs review |
| Polski | Polish | `pl` | needs review |
| Português (Brasil) | Portuguese (Brazil) | `pt_BR` | needs review |
| Svenska | Swedish | `sv` | needs review |
| Українська | Ukrainian | `uk` | reviewed |
| 简体中文 | Chinese (Simplified) | `zh_CN` | needs review |

"Needs review" means a complete first pass not yet checked by a native speaker. If something reads oddly in
your language, please fix it in `po/<code>.po` and open a pull request, or just open an issue quoting the
string and a better wording. New languages are welcome too.

## For developers

User-visible strings are English in the code and translated with gettext:

```python
from kram.i18n import _, ngettext, pgettext, N_

_("Reload")
ngettext("{n} package", "{n} packages", n).format(n=n)   # plurals
pgettext("package status", "Installed")                   # same English word, different translations
```

Use named `{placeholders}` with `.format()`, never f-strings inside `_()`.

- Update the template and all catalogs after changing strings: `scripts/i18n.sh update`
- Start a new language: `scripts/i18n.sh new <lang>` (e.g. `nl`, `zh_TW`), then translate `po/<lang>.po`;
  also add the language to `data/` (`GenericName`/`Comment`/`Keywords` in both `.desktop` files, the metainfo
  `summary` and the polkit `description`/`message`)
- Validate: `scripts/i18n.sh check` (the test suite also checks that the template is current, catalogs
  are complete, and placeholders match)
