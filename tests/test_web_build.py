from pathlib import Path

from scripts.build_web import build_site


ASSETS = ("index.html", "styles.css", "app.js", "converter-worker.js")


def test_build_site_copies_static_assets_and_wheel(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    web = root / "web"
    web.mkdir(parents=True)
    for asset in ASSETS:
        (web / asset).write_text(f"asset:{asset}\n", encoding="utf-8")
    wheel = root / "dist" / "tg2notebooklm-0.1.0-py3-none-any.whl"
    wheel.parent.mkdir()
    wheel.write_bytes(b"wheel-bytes")
    destination = tmp_path / "site"

    built_wheel = build_site(root, destination, wheel)

    assert built_wheel == destination / "packages" / wheel.name
    assert built_wheel.read_bytes() == b"wheel-bytes"
    assert (destination / ".nojekyll").is_file()
    assert all((destination / asset).read_text(encoding="utf-8") == f"asset:{asset}\n" for asset in ASSETS)
    config = (destination / "site-config.js").read_text(encoding="utf-8")
    assert './packages/tg2notebooklm-0.1.0-py3-none-any.whl' in config


def test_build_site_replaces_previous_output(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    web = root / "web"
    web.mkdir(parents=True)
    for asset in ASSETS:
        (web / asset).write_text(asset, encoding="utf-8")
    wheel = root / "dist" / "tg2notebooklm-0.1.0-py3-none-any.whl"
    wheel.parent.mkdir()
    wheel.write_bytes(b"wheel")
    destination = tmp_path / "site"
    destination.mkdir()
    stale = destination / "stale.txt"
    stale.write_text("stale", encoding="utf-8")

    build_site(root, destination, wheel)

    assert not stale.exists()


def test_web_javascript_syntax() -> None:
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        return
    checker = """
const fs = require('fs');
const path = require('path');
const vm = require('vm');
for (const name of ['app.js', 'converter-worker.js']) {
  const code = fs.readFileSync(path.join('web', name), 'utf8');
  try {
    new vm.SourceTextModule(code);
  } catch (err) {
    console.error(`Syntax error in ${name}:`, err);
    process.exit(1);
  }
}
"""
    result = subprocess.run(
        [node, "--experimental-vm-modules", "-e", checker],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Node reported syntax error:\n{result.stderr}\n{result.stdout}"
