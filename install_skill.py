"""Install the canonical Flagsmith Safe Rollout skill into Claude/Cursor/Codex directories."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SKILL_NAME = "flagsmith-safe-rollout"
TARGETS = {
    "claude": Path(".claude/skills"),
    "cursor": Path(".cursor/skills"),
    "codex": Path(".codex/skills"),
}


def install(root: Path, targets: list[str]) -> list[str]:
    source = root / ".agents" / "skills" / SKILL_NAME
    if not source.is_dir():
        raise FileNotFoundError(f"Canonical skill directory not found: {source}")

    installed: list[str] = []
    for target in targets:
        dest_dir = root / TARGETS[target] / SKILL_NAME
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(source, dest_dir)
        installed.append(str(dest_dir))
    return installed


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror canonical .agents skill to other coding agents")
    parser.add_argument("--targets", nargs="+", choices=list(TARGETS), default=["claude", "cursor"])
    args = parser.parse_args()

    paths = install(Path(__file__).resolve().parent, args.targets)
    for path in paths:
        print(f"Installed skill to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
