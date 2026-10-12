"""CLI tests: generate files, exit codes, --decode round-trip."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

import qr
from qr.decode import available_backend

HAS_NATIVE = available_backend() != "none"


@pytest.fixture(scope="module")
def cli_runner():
    """Wrap the Click group if Click is available (preferred CLI path)."""
    try:
        from click.testing import CliRunner
        from qr.cli import _make_click_cli
    except Exception:  # pragma: no cover - click always present here
        pytest.skip("click not importable")
    return CliRunner(), _make_click_cli()


def test_cli_generate_png_to_file(cli_runner):
    runner, cli = cli_runner
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "code.png"
        result = runner.invoke(cli, ["generate", "hello cli", "-o", str(out)])
        assert result.exit_code == 0, result.output
        assert out.exists()
        assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_cli_generate_svg(cli_runner):
    runner, cli = cli_runner
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "code.svg"
        result = runner.invoke(cli, ["generate", "hello", "--format", "svg", "-o", str(out)])
        assert result.exit_code == 0, result.output
        assert b"<svg" in out.read_bytes()


def test_cli_generate_ascii_stdout(cli_runner):
    runner, cli = cli_runner
    result = runner.invoke(cli, ["generate", "hello", "--format", "ascii"])
    assert result.exit_code == 0
    assert "#" in result.output


@pytest.mark.skipif(not HAS_NATIVE, reason="no pyzbar/OpenCV installed")
def test_cli_roundtrip_generate_then_decode(cli_runner):
    """Generate a QR via the CLI, decode it via the CLI, assert they match."""
    runner, cli = cli_runner
    payload = "cli-roundtrip-123"
    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / "code.png"
        gen = runner.invoke(cli, ["generate", payload, "-o", str(png)])
        assert gen.exit_code == 0, gen.output

        dec = runner.invoke(cli, ["decode", str(png)])
        assert dec.exit_code == 0, dec.output
        assert payload in dec.output


def test_cli_decode_missing_backend_graceful(cli_runner):
    """When no native backend exists, decode exits 2 with a friendly message."""
    if HAS_NATIVE:
        pytest.skip("native backend present -- handled by round-trip test")
    runner, cli = cli_runner
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        fh.write(b"not an image")
        path = fh.name
    try:
        result = runner.invoke(cli, ["decode", path])
        assert result.exit_code == 2
    finally:
        os.unlink(path)


def test_cli_write_matches_library_generate(cli_runner):
    runner, cli = cli_runner
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "code.png"
        runner.invoke(cli, ["generate", "same", "-o", str(out)])
        lib_bytes = qr.generate("same")
        assert lib_bytes == out.read_bytes()


def test_module_entry_runs(stack=""):  # pragma: no cover - subprocess smoke
    import subprocess

    # ``python -m qr generate hello --format ascii`` should succeed.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.dirname(os.path.dirname(__file__)) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "qr", "generate", "hello", "--format", "ascii"],
        capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    assert proc.returncode == 0, proc.stderr
    assert "#" in proc.stdout or "Block" in proc.stdout or "█" in proc.stdout