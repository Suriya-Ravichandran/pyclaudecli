"""`python -m pyclaudecli` — a minimal CLI wrapper for quick scripting.

For anything beyond a one-off prompt, use `pyclaudecli.ClaudeCLI` directly.
"""

from __future__ import annotations

import sys
from typing import List, Optional, Tuple

from .client import ClaudeCLI


def parse_args(argv: List[str]) -> Tuple[str, str]:
    model = "haiku"
    prompt_parts = []
    index = 0

    while index < len(argv):
        arg = argv[index]

        if arg in {"--model", "-m"}:
            if index + 1 >= len(argv):
                raise SystemExit("Missing value for --model.")
            model = argv[index + 1]
            index += 2
            continue

        if arg.startswith("--model="):
            model = arg.split("=", 1)[1]
            index += 1
            continue

        prompt_parts.append(arg)
        index += 1

    prompt = " ".join(prompt_parts).strip() if prompt_parts else "Hello, Claude!"
    return model, prompt


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    model, prompt = parse_args(argv)
    client = ClaudeCLI()
    try:
        result = client.run(["--print", "--model", model, prompt], check=False)
    except Exception as exc:  # ClaudeNotFoundError, etc.
        print(str(exc), file=sys.stderr)
        return 1

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
