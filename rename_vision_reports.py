from __future__ import annotations

import re
from pathlib import Path


def extract_vision_model(project_name: str) -> str:
    match = re.match(r"^(\d{8})_(.+)$", project_name)
    if not match:
        return project_name
    rest = match.group(2)
    if rest.endswith("_test_vision"):
        return rest[: -len("_test_vision")]
    if "_and_" in rest:
        return rest.split("_and_", 1)[0]
    return rest or project_name


def rename_reports(projects_root: Path) -> int:
    renamed = 0
    for project_dir in projects_root.iterdir():
        if not project_dir.is_dir():
            continue
        diagnostics_dir = project_dir / "diagnostics"
        old_path = diagnostics_dir / "vision_report.json"
        if not old_path.exists():
            continue
        vision_model = extract_vision_model(project_dir.name)
        new_path = diagnostics_dir / f"vision_report_{vision_model}.json"
        if new_path.exists():
            print(f"Skip (exists): {new_path}")
            continue
        old_path.rename(new_path)
        print(f"Renamed: {old_path} -> {new_path}")
        renamed += 1
    return renamed


def main() -> int:
    projects_root = Path(__file__).resolve().parent / "projects"
    if not projects_root.exists():
        raise SystemExit(f"projects folder not found: {projects_root}")
    count = rename_reports(projects_root)
    print(f"Done. Renamed {count} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
