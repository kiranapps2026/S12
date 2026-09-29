"""Fix data_sanitizer.py: convert dicts to MappingProxyType."""
import subprocess
import ast

result = subprocess.run(
    ["git", "show", "HEAD:src/contracts/data_sanitizer.py"],
    capture_output=True, text=True
)
lines = result.stdout.splitlines()

# 1. Add types import
for i, line in enumerate(lines):
    if line.strip() == "from dataclasses import dataclass, field":
        lines.insert(i + 1, "import types")
        break

# 2. Change SEVERITY_ACTION_MAP
for i, line in enumerate(lines):
    if "SEVERITY_ACTION_MAP: dict[Severity, SeverityAction] = {" in line:
        lines[i] = line.replace(
            "SEVERITY_ACTION_MAP: dict[Severity, SeverityAction] = {",
            "SEVERITY_ACTION_MAP = types.MappingProxyType({"
        )
        break

# 3. Change INJECTION_PATTERNS
for i, line in enumerate(lines):
    if "INJECTION_PATTERNS: dict[str, tuple[str, Severity]] = {" in line:
        lines[i] = line.replace(
            "INJECTION_PATTERNS: dict[str, tuple[str, Severity]] = {",
            "INJECTION_PATTERNS = types.MappingProxyType({"
        )
        break

# 4. Change closing } of INJECTION_PATTERNS to })
for i, line in enumerate(lines):
    if line.strip() == "}" and i + 1 < len(lines) and lines[i + 1].strip().startswith("@"):
        lines[i] = "})"
        break

output = "\n".join(lines)

# Verify it parses
try:
    ast.parse(output)
    with open("src/contracts/data_sanitizer.py", "w") as f:
        f.write(output)
    print("SUCCESS")
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")
