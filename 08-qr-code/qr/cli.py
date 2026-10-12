"""Command-line interface for the ``qr`` package.

Provides the ``qr`` command:

    qr "https://example.com"                # PNG to stdout (or --output)
    qr "hello" -o code.png                  # save PNG
    qr "hello" --format svg -o code.svg     # SVG file
    qr "hello" --format ascii              # plain ASCII art on stdout
    qr "hello" --format terminal           # Unicode block art
    qr --decode qrcode.png                 # decode an image -> payload

Uses **Click** when importable (the preferred CLI framework), else a small
argparse shim so the tool still works on a minimal install.

Exit codes:
    - 0 success
    - 1 unexpected error
    - 2 decode failed (no QR / backend missing / unreadable image)
"""

from __future__ import annotations

import sys
from typing import Optional

try:  # pragma: no cover - exercised only on a minimal install
    import click
except Exception:  # pragma: no cover
    click = None  # type: ignore[assignment]

from . import config as _config

# ``qr.decode`` (the package attribute) is the exported *function*, so import
# the underlying module object explicitly to reach ``DecodeError``/``decode``.
import importlib as _importlib

_decode_mod = _importlib.import_module("qr.decode")

__all__ = ["main", "cli"]

#: Exit code used when decoding fails (spec: friendly message, exit 2).
DECODE_ERROR_EXIT = 2


# --------------------------------------------------------------------------- #
# Shared generation / decode helpers (used by Click + argparse + tests)
# --------------------------------------------------------------------------- #


def render(data: str, fmt: str = "png", size: int = _config.DEFAULT_SIZE,
           ec_level: str = _config.DEFAULT_EC_LEVEL.value):
    """Render ``data`` in ``fmt``; PNG/SVG return bytes, ascii/terminal a str."""
    import importlib

    # The ``qr.generate`` name is the *function* exported by the package, so
    # import the underlying module object explicitly.
    _gen = importlib.import_module("qr.generate")
    return _gen.generate(data, format=fmt, size=size, ec_level=ec_level)


def cli_generate(
    data: str,
    *,
    fmt: str = "png",
    output: Optional[str] = None,
    size: int = _config.DEFAULT_SIZE,
    ec_level: str = _config.DEFAULT_EC_LEVEL.value,
) -> None:
    """Render a QR for ``data`` and write to ``output`` (or stdout)."""
    result = render(data, fmt=fmt, size=size, ec_level=ec_level)

    if output:
        # Binary formats (PNG/SVG) are written raw; text formats use UTF-8.
        binary = isinstance(result, bytes)
        with open(output, "wb" if binary else "w", encoding=None if binary else "utf-8") as fh:
            fh.write(result)
        print(f"Wrote {fmt.upper()} QR to {output}")
        return

    # No output flag: put bytes on stdout.buffer, text on stdout.
    if isinstance(result, bytes):
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write(result)
        if not result.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()


def decode_image_for_cli(image: str) -> _decode_mod.DecodeResult:
    """Decode ``image`` via :func:`qr.decode.decode`, raising DecodeError."""
    return _decode_mod.decode(image)


def _report_backend() -> str:
    """Return the active decode backend name for diagnostics."""
    import importlib

    _gen = importlib.import_module("qr.generate")
    backend = _decode_mod.available_backend()
    gen_backend = _gen.current_backend_name()
    return f"decode backend: {backend}; generate backend: {gen_backend}"


# --------------------------------------------------------------------------- #
# Click entrypoint (preferred)
# --------------------------------------------------------------------------- #


def _make_click_cli() -> "click.Group":
    @click.group()
    @click.version_option(package_name="qr")
    def cli() -> None:
        """Generate and decode QR codes (PNG / SVG / ASCII / terminal)."""

    @cli.command("generate")
    @click.argument("data")
    @click.option("--output", "-o", "output", default=None,
                  help="Write the code to FILE (default: stdout / PNG bytes).")
    @click.option("--format", "-f", "fmt", default="png",
                  type=click.Choice(_config.SUPPORTED_FORMATS),
                  help="Output format: png, svg, ascii or terminal.")
    @click.option("--size", "-s", "size", default=_config.DEFAULT_SIZE, type=int,
                  help="Pixel size for raster (PNG) output.")
    @click.option("--error-correction", "-e", "ec", default=_config.DEFAULT_EC_LEVEL.value,
                  type=click.Choice(_config.ERROR_CORRECTION_CHOICES),
                  help="Error-correction level (L/M/Q/H).")
    def generate(data, output, fmt, size, ec):
        """Encode DATA into a QR code."""
        try:
            cli_generate(data, fmt=fmt, output=output, size=size, ec_level=ec)
        except ValueError as exc:
            raise click.ClickException(str(exc))

    @cli.command("decode")
    @click.argument("image", type=click.Path(exists=True))
    @click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON.")
    def decode(image, as_json):
        """Decode a QR code from IMAGE (PNG/JPG/BMP/GIF...)."""
        try:
            result = decode_image_for_cli(image)
        except _decode_mod.DecodeError as exc:
            click.echo(f"qr: decode failed: {exc}", err=True)
            raise click.exceptions.Exit(DECODE_ERROR_EXIT)
        if as_json:
            import json

            click.echo(json.dumps({
                "data": result.data,
                "version": result.version,
                "ec_level": result.ec_level,
                "backend": result.backend,
            }))
        else:
            click.echo(f"Data: {result.data}")
            if result.version:
                click.echo(f"Version: {result.version}")
            if result.ec_level:
                click.echo(f"EC level: {result.ec_level}")

    @cli.command("backend")
    def backend():
        """Print the active decode backend and exit."""
        click.echo(_report_backend())

    return cli


# --------------------------------------------------------------------------- #
# Primary entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    """The ``qr`` console entry point."""
    args = sys.argv[1:]

    # ``--decode`` anywhere selects decode mode; otherwise it is generation.
    if "--decode" in args:
        _run_decode_mode(args)
        return

    if click is not None:
        _make_click_cli()(prog_name="qr")
        return

    _main_argparse(args)  # pragma: no cover - no-click fallback


def _run_decode_mode(argv) -> None:
    rest = [a for a in argv if a != "--decode"]
    image = rest[-1] if rest else None
    if not image:
        click.echo("qr: --decode requires an image path", err=True) if click else None
        sys.stderr.write("qr: --decode requires an image path\n")
        sys.exit(DECODE_ERROR_EXIT)
    try:
        result = decode_image_for_cli(image)
    except _decode_mod.DecodeError as exc:
        sys.stderr.write(f"qr: decode failed: {exc}\n")
        sys.exit(DECODE_ERROR_EXIT)
    sys.stdout.write(result.data + "\n")


# --------------------------------------------------------------------------- #
# argparse fallback
# --------------------------------------------------------------------------- #


def _main_argparse(argv) -> None:  # pragma: no cover - used only without click
    import argparse

    p = argparse.ArgumentParser(prog="qr", description="Generate and decode QR codes.")
    sub = p.add_subparsers(dest="command")

    gen = sub.add_parser("generate")
    gen.add_argument("data")
    gen.add_argument("-o", "--output", default=None)
    gen.add_argument("-f", "--format", default="png", choices=_config.SUPPORTED_FORMATS)
    gen.add_argument("-s", "--size", type=int, default=_config.DEFAULT_SIZE)
    gen.add_argument("-e", "--error-correction", default=_config.DEFAULT_EC_LEVEL.value,
                     choices=_config.ERROR_CORRECTION_CHOICES)

    dec = sub.add_parser("decode")
    dec.add_argument("image")

    args = p.parse_args(argv)
    if getattr(args, "command", None) == "decode":
        try:
            result = decode_image_for_cli(args.image)
        except _decode_mod.DecodeError as exc:
            print(f"qr: decode failed: {exc}", file=sys.stderr)
            sys.exit(DECODE_ERROR_EXIT)
        print(result.data)
    elif getattr(args, "command", None) == "generate":
        cli_generate(args.data, fmt=args.format, output=args.output, size=args.size,
                     ec_level=args.error_correction)
    else:
        p.print_help()


if __name__ == "__main__":  # pragma: no cover - direct invocation
    main()