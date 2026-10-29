"""Run the accepted full-source packager with this release directory as output."""

from pathlib import Path


source = Path(__file__).resolve().parents[1] / "default-workbench-20261026" / "package_source.py"
exec(compile(source.read_bytes(), source.as_posix(), "exec"))
