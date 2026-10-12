# QR Code Generator + Decoder

## Project Title
QR Code Generator & Decoder (Python)

## Goal
Generate QR codes from any text/URL. Decode QR codes from images. Support multiple output formats (PNG, SVG, terminal ASCII art).

## Why this project
Binary data encoding, error correction, image processing. Teaches how QR codes actually work (Reed-Solomon error correction is fascinating).

## What You Build
A `qr` command:

```bash
qr "https://example.com"               # PNG to stdout or save
qr "hello" -o code.png                 # save PNG
qr "hello" --format svg -o code.svg    # SVG
qr "hello" --format ascii              # terminal display
qr "hello" --format terminal            # Unicode block art
qr --decode qrcode.png                 # decode image
qr --decode qrcode.jpg                 # decode any image
```

Library:
```python
from qr import generate, decode

# Generate
png_bytes = generate("hello world", format="png", size=300)
svg_str = generate("hello world", format="svg")

# Decode
text = decode("qrcode.png")
```

## Tech
- **Python 3.11+**
- **qrcode** library (generation)
- **Pillow** (PNG manipulation)
- **OpenCV** or **pyzbar** (decoding)
- **Click** for CLI
- **rich** for terminal display

## Architecture

```
qr/
├── qr/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py              # Click commands
│   ├── generate.py         # QR generation (wraps qrcode lib)
│   ├── decode.py           # QR decoding (wraps pyzbar)
│   ├── formats.py          # PNG, SVG, ASCII, terminal
│   ├── ascii_art.py        # Unicode block art for terminal
│   └── config.py           # Default size, error correction
├── tests/
│   ├── test_generate.py
│   ├── test_decode.py
│   └── test_formats.py
├── pyproject.toml
└── CLAUDE.md
```

## Build Order

1. **`generate.py`** — wrap `qrcode` lib, return PIL Image + SVG string
2. **`decode.py`** — wrap pyzbar, accept image path or bytes
3. **`formats.py`** — PNG save, SVG save, stdout output
4. **`ascii_art.py`** — convert QR matrix to Unicode block art (█▀▄ chars)
5. **`cli.py`** — Click app with subcommands
6. **`__main__.py`** — entry point
7. **Tests** — generate known QR, decode it, verify match

## Requirements

- Generation supports all error correction levels (L=7%, M=15%, Q=25%, H=30%)
- Generation supports 4 output formats: PNG, SVG, ASCII (plain), Unicode block art
- Generation accepts text up to 4296 alphanumeric chars (max QR capacity)
- Generation produces scannable codes (test by scanning with your phone)
- Decoding accepts PNG, JPG, BMP, GIF (all common formats)
- Decoding returns text + format version + error correction level
- CLI handles both generation and decoding (subcommands)
- Auto-detect from `--decode` flag vs no flag

## Code Standards

- All public functions have type hints
- CLI uses Click decorators, not manual argparse
- QR generation never writes to disk unless `--output` flag given
- Decode errors (can't find QR) return friendly message, exit code 2
- Tests verify round-trip: generate → save → decode → assert equal

## Verification

```bash
pip install -e .

# Generate
qr "https://github.com" -o test.png
qr "https://github.com" --format svg -o test.svg
qr "https://github.com" --format ascii

# Decode (use generated PNG)
qr --decode test.png

# Round trip test
pytest tests/ -v
```

## Stretch Goals

- Generate QR codes with logos in the center (logo embedding)
- Generate vCard QR codes (contact cards)
- Generate WiFi QR codes (network name + password)
- Generate batch QR codes from CSV
- Webcam-based decode (live camera)
- Error correction customization (which bits to lose gracefully)
- Color customization (foreground/background)
- Micro QR codes (smaller, for tiny spaces)

## What You'll Learn

- QR code data encoding (numeric, alphanumeric, byte, kanji modes)
- Reed-Solomon error correction (fascinating math)
- Image generation and decoding
- Binary data serialization
- Unicode block character rendering
- Multiple output format handling

## Time Estimate
2-3 hours for generation only. 5-7 hours with decoding + multiple formats + tests.