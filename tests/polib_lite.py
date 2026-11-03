"""Just enough .po parsing for the tests (no third-party dependency)."""
import ast


def entries(text: str):
    for block in text.split("\n\n"):
        entry, cur = {"msgstr": []}, None
        for line in block.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            if line.startswith('"'):
                value = ast.literal_eval(line)
                if cur == "msgstr":
                    entry["msgstr"][-1] += value
                else:
                    entry[cur] += value
                continue
            key, _, rest = line.partition(" ")
            value = ast.literal_eval(rest)
            if key.startswith("msgstr"):
                cur = "msgstr"
                entry["msgstr"].append(value)
            else:
                cur = key
                entry[key] = value
        if entry.get("msgid"):
            yield entry
