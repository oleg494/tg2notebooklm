from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Sequence

STATIC_ASSETS = ("index.html", "styles.css", "app.js", "converter-worker.js")
PYODIDE_VERSION = "314.0.6"
PYODIDE_INDEX_URL = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"


def build_site(repo_root: Path, destination: Path, wheel: Path) -> Path:
    repo_root = Path(repo_root).resolve()
    destination = Path(destination).resolve()
    wheel = Path(wheel).resolve()
    web_root = repo_root / "web"

    missing = [name for name in STATIC_ASSETS if not (web_root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing web assets: {', '.join(missing)}")
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise FileNotFoundError(f"Wheel not found: {wheel}")

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for name in STATIC_ASSETS:
        shutil.copyfile(web_root / name, destination / name)

    package_dir = destination / "packages"
    package_dir.mkdir()
    built_wheel = package_dir / wheel.name
    shutil.copyfile(wheel, built_wheel)

    config = {
        "pyodideIndexURL": PYODIDE_INDEX_URL,
        "wheelPath": f"./packages/{wheel.name}",
    }
    config_json = json.dumps(config, ensure_ascii=True, indent=2)
    (destination / "site-config.js").write_text(
        f"export const APP_CONFIG = Object.freeze({config_json});\n",
        encoding="utf-8",
        newline="\n",
    )
    (destination / ".nojekyll").write_text("", encoding="utf-8")
    return built_wheel


def _find_wheel(repo_root: Path) -> Path:
    wheels = sorted((repo_root / "dist").glob("tg2notebooklm-*.whl"))
    if not wheels:
        raise FileNotFoundError("No tg2notebooklm wheel in dist/. Run `uv build --wheel` first.")
    return wheels[-1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static GitHub Pages site")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("_site"))
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args(argv)

    root = args.repo_root.resolve()
    wheel = args.wheel.resolve() if args.wheel else _find_wheel(root)
    built_wheel = build_site(root, args.output, wheel)
    print(f"Built {args.output.resolve()} with {built_wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
