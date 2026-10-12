"""Click-based command-line interface for md2html.

Public command: ``md2html FILE.md [-o OUTDIR] [--theme THEME] [--toc] [--serve]``

The entry point is ``main`` (a Click ``Group``) so both ``python -m md2html``
and a console-script install resolve to the same command. All errors exit with
a non-zero code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Tuple

import click

from .config import validate_theme
from .converter import convert
from .serve import run_server

__all__ = ["main"]


def _write_one(src: Path, out: Path, theme: str) -> None:
    """Convert a single file to ``out``.

    Args:
        src: Source Markdown file.
        out: Destination ``.html`` path.
        theme: CSS theme name for the output.

    Raises:
        OSError / UnicodeDecodeError: Propagated so the caller can report the
            offending path with a non-zero exit code.
    """
    text = src.read_text(encoding="utf-8")
    html = convert(text, theme=theme)
    out.write_text(html, encoding="utf-8")


def _destination(src: Path, out_dir: Optional[Path]) -> Path:
    """Compute the output path for ``src``."""
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / (src.stem + ".html")
    return src.with_suffix(".html")


def _expand_inputs(files: Tuple[str, ...]) -> Tuple[Path, ...]:
    """Glob directory and wildcard patterns in ``files`` into concrete paths."""
    expanded: list[Path] = []
    for raw in files:
        p = Path(raw)
        if any(c in raw for c in "*?[") or p.is_dir():
            # Treat as a glob pattern or directory.
            pattern = (p / "*.md") if p.is_dir() else p
            matches = sorted(pattern.parent.glob(pattern.name))
            expanded.extend(m for m in matches if m.is_file())
        else:
            expanded.append(p)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = [p for p in expanded if not (str(p) in seen or seen.add(str(p)))]
    return tuple(unique)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "files",
    nargs=-1,
    required=True,
    metavar="FILE_OR_GLOB [FILE_OR_GLOB ...]",
)
@click.option(
    "-o",
    "--out-dir",
    "out_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory to write generated .html files into.",
)
@click.option(
    "--theme",
    default="light",
    show_default=True,
    type=click.Choice(["light", "dark", "solarized"], case_sensitive=False),
    help="CSS theme for the output document.",
)
@click.option(
    "--toc",
    is_flag=True,
    default=False,
    help="Force a table of contents into the output.",
)
@click.option(
    "--serve",
    is_flag=True,
    default=False,
    help="Start a local preview server instead of writing files.",
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Bind address for --serve.",
)
@click.option(
    "--port",
    default=8000,
    show_default=True,
    type=int,
    help="TCP port for --serve.",
)
@click.version_option(package_name="md2html", prog_name="md2html")
def main(
    files: Tuple[str, ...],
    out_dir: Optional[Path],
    theme: str,
    toc: bool,
    serve: bool,
    host: str,
    port: int,
) -> None:
    """Convert Markdown files to standalone HTML documents.

    Examples:

        md2html README.md                      # writes README.html

        md2html posts/*.md -o dist/             # batch convert into dist/

        md2html doc.md --theme dark --toc       # dark theme + table of contents

        md2html README.md --serve               # open a local preview server
    """
    theme = validate_theme(theme)

    if serve:
        _serve(files, theme, host, port)
        return

    sources = _expand_inputs(files)
    if not sources:
        click.echo("md2html: no input files matched.", err=True)
        sys.exit(1)

    failure = False
    for src in sources:
        dest = _destination(src, out_dir)
        try:
            _write_one(src, dest, theme)
        except (OSError, UnicodeDecodeError) as exc:  # noqa: B014
            click.echo(
                f"md2html: failed to convert {src}: {exc}", err=True
            )
            failure = True
            continue
        click.echo(f"wrote {dest}")

    if failure:
        sys.exit(1)


def _serve(files: Tuple[str, ...], theme: str, host: str, port: int) -> None:
    """Render everything and hand control to the preview server."""
    sources = _expand_inputs(files)
    if not sources:
        click.echo(
            "md2html: --serve needs at least one matching input file.", err=True
        )
        sys.exit(1)
    from .serve import servers

    backend = "FastAPI + uvicorn" if servers["fastapi"] else "stdlib http.server"
    click.echo(
        f"md2html: previewing {len(sources)} file(s) at "
        f"http://{host}:{port}/ via {backend}"
    )
    run_server(sources, theme, host=host, port=port, open_browser=True)


if __name__ == "__main__":
    main()