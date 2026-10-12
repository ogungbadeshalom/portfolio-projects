"""Tests for the md2html library and CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from md2html import convert
from md2html.config import Options, validate_theme, PYDANTIC_LOADED
from md2html.themes import THEME_NAMES


# --------------------------------------------------------------------------- #
# Library: convert()
# --------------------------------------------------------------------------- #
def test_convert_produces_full_html_document() -> None:
    """Output must be a complete, standalone HTML page with the theme's CSS."""
    html = convert("# Hello\n\nSome *text*.")
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "<html" in html
    assert "<style>" in html
    assert "Hello" in html


def test_convert_escapes_fenced_code_content() -> None:
    """Raw code inside fenced blocks must be HTML-escaped, never injected."""
    html = convert("# C\n\n```\n<script>alert(1)</script>\n```")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_convert_theme_is_embedded() -> None:
    """Each registered theme name should produce distinct CSS in the output."""
    for theme in THEME_NAMES:
        html = convert("# T", theme=theme)
        assert "--" in html or "background" in html, f"no CSS for {theme}"


def test_convert_all_known_themes_are_valid() -> None:
    """Validate every registered theme via the public validator."""
    for theme in THEME_NAMES:
        assert validate_theme(theme) == theme


def test_validate_theme_rejects_unknown() -> None:
    """An unknown theme must raise with helpful choices."""
    with pytest.raises(ValueError):
        validate_theme("neon")
    err = None
    try:
        validate_theme("neon")
    except ValueError as exc:
        err = str(exc)
    assert err is not None and "light" in err


def test_convert_heading_content_rendered() -> None:
    """A markdown heading should appear in the rendered body."""
    html = convert("# Big Heading")
    assert "<h1" in html
    assert "Big Heading" in html


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_options_default_toc_off() -> None:
    """Options() should default to light theme and no TOC."""
    if not PYDANTIC_LOADED:
        pytest.skip("pydantic not available")
    opts = Options()
    assert opts.theme == "light"
    assert opts.toc is False


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
@pytest.fixture
def sample_md(tmp_path: Path) -> Path:
    """A sample markdown file to convert via the CLI."""
    src = tmp_path / "post.md"
    src.write_text("# Post Title\n\nA body paragraph.", encoding="utf-8")
    return src


def _run_cli(*args: str) -> tuple[int, str]:
    from click.testing import CliRunner
    from md2html.cli import main

    runner = CliRunner()
    result = runner.invoke(main, list(args))
    return result.exit_code, result.output


def test_cli_converts_single_file(sample_md: Path, tmp_path: Path) -> None:
    """`md2html FILE.md` writes FILE.html next to it."""
    code, out = _run_cli(str(sample_md))
    assert code == 0, out
    output = sample_md.with_suffix(".html")
    assert output.exists()
    assert "<!DOCTYPE html>" in output.read_text(encoding="utf-8")


def test_cli_converts_into_out_dir(sample_md: Path, tmp_path: Path) -> None:
    """`-o DIR` must place the output HTML in DIR."""
    out_dir = tmp_path / "dist"
    code, out = _run_cli(str(sample_md), "-o", str(out_dir))
    assert code == 0, out
    assert (out_dir / "post.html").exists()


def test_cli_rejects_unknown_theme(sample_md: Path) -> None:
    """Click's choice validation rejects an unknown --theme."""
    code, out = _run_cli(str(sample_md), "--theme", "neon")
    assert code != 0
    assert "neon" in out or "not one of" in out


def test_cli_no_input_files_is_error(tmp_path: Path) -> None:
    """A glob that matches nothing should exit non-zero."""
    code, out = _run_cli(str(tmp_path / "nothing*.md"))
    assert code == 1