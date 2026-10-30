"""Quote catalog values that contain ': ' or ' #' (plain YAML scalars cannot). Usage: python scripts/fix_yaml_quotes.py <files...>"""
import re, sys, yaml

pat = re.compile(r'^(\s*)([A-Za-z0-9_]+):\s+(.*)$')
for f in sys.argv[1:]:
    out, changed = [], 0
    for line in open(f, encoding="utf-8").read().split("\n"):
        m = pat.match(line)
        if m and not line.lstrip().startswith("#"):
            ind, k, v = m.groups()
            if v and v[0] not in "\"'|>[{&*!" and (": " in v or " #" in v or v.endswith(":")):
                line = f'{ind}{k}: "' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'; changed += 1
        out.append(line)
    open(f, "w", encoding="utf-8").write("\n".join(out))
    yaml.safe_load(open(f, encoding="utf-8")); print("ok", f, changed)
