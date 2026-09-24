"""Validate inline JavaScript embedded in Jinja templates."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


TEMPLATES = (
    Path("templates/index.html"),
    Path("WebRTC_Meet/templates/client.html"),
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="wewatch-js-") as temp_dir:
        temp = Path(temp_dir)
        for template in TEMPLATES:
            source = template.read_text(encoding="utf-8")
            scripts = re.findall(r"<script[^>]*>(.*?)</script>", source, re.S | re.I)
            for index, script in enumerate(scripts):
                script = re.sub(r"\{\{.*?\}\}", "PLACEHOLDER", script, flags=re.S)
                script = re.sub(r"\{%.*?%\}", "", script, flags=re.S)
                output = temp / f"{template.stem}-{index}.js"
                output.write_text(script, encoding="utf-8")
                result = subprocess.run(
                    ["node", "--check", str(output)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode:
                    print(f"{template}:{index}: {result.stderr.strip()}")
                    return result.returncode
    print("template_javascript_syntax_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())