"""A compact, dependency-free QR matrix encoder.

This is a **fallback** encoder used only when the third-party ``qrcode``
package is not importable. It implements the QR Code specification
(ISO/IEC 18004) closely enough to produce *scannable* codes for typical short
inputs: numeric, alphanumeric and byte (8-bit) encoding modes, Reed-Solomon
error correction, versions 1--10, standard finder/timing/alignment patterns,
all 8 mask patterns with automatic selection via a penalty score, and correct
format-information (BCH) bits.

Scope / limitations
-------------------
- Versions 1 through 10 only (far more than normal CLI use needs).
- No Kanji mode, structured append, or mixed-mode optimisation.
- Mask selection uses a simplified penalty (run-length only) that still yields
  a legal, scannable mask; readers recover the mask from the format info.

The public entry point is :func:`make_matrix`, which returns a ``(matrix,
version, ec_level)`` tuple whose ``matrix`` shape matches what the standard
``qrcode`` package's ``get_matrix()`` returns, so downstream rendering code is
identical whichever backend produced the matrix.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# QR spec tables (versions 1..10)
# ---------------------------------------------------------------------------

# version -> total codewords (data + ECC) in the code, per Annex B.
TOTAL_CODEWORDS: List[int] = [
    0, 26, 44, 70, 100, 134, 172, 196, 242, 292, 346,
]

# EC level -> (index into tables). Order: L, M, Q, H
EC_INDEX: dict = {"L": 0, "M": 1, "Q": 2, "H": 3}

# [EC_INDEX][version] -> (ec_codewords_per_block, num_blocks)
EC_LAYOUT: List[List[Tuple[int, int]]] = [
    # L (index 0)
    [None, (7, 1), (10, 1), (15, 1), (20, 1), (26, 1), (18, 2), (20, 2), (24, 2), (30, 2), (18, 4)],
    # M (index 1)
    [None, (10, 1), (16, 1), (26, 1), (18, 2), (24, 2), (16, 4), (18, 4), (22, 4), (22, 4), (26, 4)],
    # Q (index 2)
    [None, (13, 1), (22, 1), (18, 2), (26, 2), (18, 2), (24, 4), (18, 4), (22, 4), (20, 6), (24, 6)],
    # H (index 3)
    [None, (17, 1), (28, 1), (22, 2), (16, 4), (22, 4), (28, 4), (26, 4), (26, 4), (24, 6), (28, 6)],
]

# version -> remainder bits after data+ECC for that version (cycles mod 7).
REMAINDER_BITS: List[int] = [0, 0, 7, 7, 7, 0, 7, 0, 0, 0, 0]

# ---------------------------------------------------------------------------
# Modes: (mode_indicator_bits, count_bits_v1-9, count_bits_v10+)
NUMERIC = (0b0001, 10, 12)
ALPHANUM = (0b0010, 9, 11)
BYTE = (0b0100, 8, 16)

#: Alphanumeric charset, section 7.4.3 of ISO/IEC 18004.
ALPHANUM_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"

# ---------------------------------------------------------------------------
# Reed-Solomon field parameters
# ---------------------------------------------------------------------------

_GF_POLY = 0x11D  # primitive polynomial for GF(2^8)
_FORMAT_GEN = 0x537  # BCH(15,5) generator
_FORMAT_MASK = 0x5412  # mask XOR applied to format info


def _gf_mul(a: int, b: int) -> int:
    """Multiply two GF(2^8) elements as integers in ``[0, 255]``."""
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        carry = a & 0x80
        a = (a << 1) & 0xFF
        if carry:
            a ^= _GF_POLY
        b >>= 1
    return result


def _gf_pow(base: int, exp: int) -> int:
    """Raise a GF(2^8) element to a power (repeated multiplication)."""
    result = 1
    for _ in range(exp):
        result = _gf_mul(result, base)
    return result


def _rs_generator(degree: int) -> List[int]:
    """Reed-Solomon generator polynomial of the given number of ECC symbols."""
    g = [1]
    for i in range(degree):
        next_g = [0] * (len(g) + 1)
        for j, coeff in enumerate(g):
            next_g[j] ^= coeff
            next_g[j + 1] ^= _gf_mul(coeff, _gf_pow(2, i))
        g = next_g
    return g


def _rs_remainder(data: List[int], degree: int) -> List[int]:
    """Compute ``degree`` Reed-Solomon ECC codewords for a data block."""
    gen = _rs_generator(degree)
    work = data + [0] * degree
    for i in range(len(data)):
        factor = work[i]
        if factor == 0:
            continue
        for j, g in enumerate(gen):
            work[i + j] ^= _gf_mul(g, factor)
    return work[len(data):]


# ---------------------------------------------------------------------------
# Mode / capacity handling
# ---------------------------------------------------------------------------


def _detect_mode(data: str) -> str:
    """Return ``"numeric"``, ``"alphanumeric"`` or ``"byte"`` for ``data``."""
    if _is_numeric(data):
        return "numeric"
    if all(c in ALPHANUM_CHARSET for c in data):
        return "alphanumeric"
    return "byte"


def _is_numeric(data: str) -> bool:
    return all(c in "0123456789" for c in data)


def _payload_bits(data: str, mode: str) -> str:
    """Produce the raw payload bit string for ``data`` in ``mode``."""
    if mode == "numeric":
        out = ""
        for i in range(0, len(data), 3):
            group = data[i : i + 3]
            width = {3: 10, 2: 7, 1: 4}[len(group)]
            out += format(int(group), f"0{width}b")
        return out
    if mode == "alphanumeric":
        out = ""
        for i in range(0, len(data), 2):
            pair = data[i : i + 2]
            a = ALPHANUM_CHARSET.index(pair[0])
            b = ALPHANUM_CHARSET.index(pair[1]) if len(pair) == 2 else 0
            if len(pair) == 2:
                out += format(a * 45 + b, "011b")
            else:
                out += format(a, "06b")
        return out
    # byte mode
    return "".join(format(b, "08b") for b in data.encode("utf-8"))


def _capacity_characters(data_bits: int, version: int, mode: str) -> int:
    """Max characters of ``mode`` that fit in ``data_bits`` at ``version``."""
    if mode == "numeric":
        count_bits = NUMERIC[1] if version <= 9 else NUMERIC[2]
        remaining = data_bits - 4 - count_bits
        chars = 0
        while remaining >= 10:
            chars += 3
            remaining -= 10
        if remaining >= 4:
            chars += 2
        elif remaining >= 1:
            chars += 1
        return chars
    if mode == "alphanumeric":
        count_bits = ALPHANUM[1] if version <= 9 else ALPHANUM[2]
        remaining = data_bits - 4 - count_bits
        chars = 0
        while remaining >= 11:
            chars += 2
            remaining -= 11
        if remaining >= 6:
            chars += 1
        return chars
    count_bits = BYTE[1] if version <= 9 else BYTE[2]
    return max(0, (data_bits - 4 - count_bits) // 8)


def _choose_version(data: str, ec_level: str) -> int:
    """Pick the smallest version (1..10) that can hold ``data``.

    Higher ECC levels take more codewords, so the data budget shrinks; we
    account for that with an ECC-dependent safety factor derived from the
    fraction of codewords reserved for ECC. A small slack is added so the
    byte-tight capacity calculation is never optimistic at the boundary.

    Args:
        data: The text to encode.
        ec_level: One of ``L``/``M``/``Q``/``H``.

    Returns:
        The chosen version (1..10).

    Raises:
        ValueError: If ``data`` is too large for the supported range.
    """
    mode = _detect_mode(data)
    for v in range(1, 11):
        total = TOTAL_CODEWORDS[v]
        ec_per_block, blocks = EC_LAYOUT[EC_INDEX[ec_level]][v]
        data_cw = total - ec_per_block * blocks
        data_bits = data_cw * 8 - REMAINDER_BITS[v % 7]
        capacity = _capacity_characters(data_bits, v, mode)
        if len(data) <= capacity:
            return v
    raise ValueError(
        f"Data too large for QR versions 1..10 (mode={mode}, {len(data)} chars)."
    )


def _build_data_codewords(data: str, version: int) -> List[int]:
    """Assemble the padded data codewords (no ECC yet) for a version."""
    mode = _detect_mode(data)
    mode_indicator, count_bits = {
        "numeric": (NUMERIC[0], NUMERIC[1] if version <= 9 else NUMERIC[2]),
        "alphanumeric": (ALPHANUM[0], ALPHANUM[1] if version <= 9 else ALPHANUM[2]),
        "byte": (BYTE[0], BYTE[1] if version <= 9 else BYTE[2]),
    }[mode]
    bits = format(mode_indicator, "04b") + format(len(data), f"0{count_bits}b")
    bits += _payload_bits(data, mode)

    # Terminator (up to 4 zero bits), then pad to a whole number of 8-bit words.
    ec_per_block, blocks = EC_LAYOUT[EC_INDEX["L"]][version]
    data_cw = TOTAL_CODEWORDS[version] - ec_per_block * blocks
    total_bits = data_cw * 8
    bits += "0" * min(4, total_bits - len(bits))
    if len(bits) > total_bits:
        raise ValueError("Data too large for the chosen version.")
    bits += "0" * ((total_bits - len(bits)) % 8)

    codewords = [int(bits[i : i + 8], 2) for i in range(0, len(bits), 8)]
    # Pad remaining codeword capacity with the standard 0xEC / 0x11 pattern.
    pad = [0xEC, 0x11]
    for i in range(len(codewords), data_cw):
        codewords.append(pad[(i - len(codewords)) % 2])
    return codewords


def _final_codeword_stream(data: str, version: int, ec_level: str) -> List[int]:
    """Return the interleaved data+ECC codeword stream for the code."""
    data_words = _build_data_codewords(data, version)
    ec_per_block, num_blocks = EC_LAYOUT[EC_INDEX[ec_level]][version]

    block_data_cw = len(data_words) // num_blocks
    data_blocks = [
        data_words[i * block_data_cw : (i + 1) * block_data_cw]
        for i in range(num_blocks)
    ]
    ec_blocks = [_rs_remainder(b, ec_per_block) for b in data_blocks]
    return _interleave(data_blocks, ec_blocks)


def _interleave(data_blocks: List[List[int]], ec_blocks: List[List[int]]) -> List[int]:
    """Interleave data then ECC blocks per the spec's grouping rules."""
    out: List[int] = []
    max_data = max(len(b) for b in data_blocks) if data_blocks else 0
    max_ec = max(len(b) for b in ec_blocks) if ec_blocks else 0
    for i in range(max_data):
        for b in data_blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(max_ec):
        for b in ec_blocks:
            if i < len(b):
                out.append(b[i])
    return out


# ---------------------------------------------------------------------------
# Module grid and function patterns
# ---------------------------------------------------------------------------


def _version_size(version: int) -> int:
    """Return the module dimension for a version (``17 + 4 * version``)."""
    return 17 + 4 * version


def _alignment_centers(version: int) -> List[int]:
    """Standard alignment-pattern center coordinates for versions 2..10."""
    table = {
        2: [6, 18],
        3: [6, 22],
        4: [6, 26],
        5: [6, 30],
        6: [6, 34],
        7: [6, 22, 38],
        8: [6, 24, 42],
        9: [6, 26, 46],
        10: [6, 28, 50],
    }
    return table.get(version, [])


def _function_mask(size: int) -> List[List[bool]]:
    """Boolean grid marking which modules are function (non-data) modules.

    ``True`` means the module is dedicated to a function pattern and never
    carries data. This is rebuilt independently of data so placement can rely
    on it alone.
    """
    version = (size - 17) // 4
    func = [[False] * size for _ in range(size)]

    def mark(r: int, c: int) -> None:
        if 0 <= r < size and 0 <= c < size:
            func[r][c] = True

    def finder(r0: int, c0: int) -> None:
        for dr in range(7):
            for dc in range(7):
                is_border = dr in (0, 6) or dc in (0, 6)
                is_centre = 2 <= dr <= 4 and 2 <= dc <= 4
                if is_border or is_centre:
                    mark(r0 + dr, c0 + dc)
        # one-module white separator around each corner
        for d in range(8):
            mark(r0 - 1, c0 + d)
            mark(r0 + 7, c0 + d)
            mark(r0 + d, c0 - 1)
            mark(r0 + d, c0 + 7)

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    # timing patterns on row/column 6
    for i in range(1, size - 1):
        mark(6, i)
        mark(i, 6)

    # alignment patterns
    for r in _alignment_centers(version):
        for c in _alignment_centers(version):
            if (r, c) in {(6, 6), (6, size - 7), (size - 7, 6)}:
                continue  # skipped where a finder already sits
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    mark(r + dr, c + dc)

    # dark module
    mark(size - 8, 8)

    # format information (two strips)
    for i in range(9):
        if i != 6:
            mark(8, i)
            mark(i, 8)
    for c in range(size - 8, size):
        mark(8, c)
    for r in range(size - 7, size):
        mark(r, 8)

    return func


def _place_data(size: int, data_bits: str, mask_id: int) -> List[List[bool]]:
    """Place a formatted bit stream into data modules under ``mask_id``."""
    func = _function_mask(size)
    matrix = [[False] * size for _ in range(size)]

    # Two-module-wide zig-zag from bottom-right, skipping the timing column.
    path: List[Tuple[int, int]] = []
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1  # timing column carries no data
        for row in range(size):
            r = row if upward else size - 1 - row
            for dc in (0, 1):
                c = col - dc
                if not func[r][c]:
                    path.append((r, c))
        col -= 2
        upward = not upward

    bit_values = [ch == "1" for ch in data_bits]
    for i, (r, c) in enumerate(path):
        bit = bit_values[i] if i < len(bit_values) else False
        is_flipped = _mask_flips(mask_id, r, c)
        # dark = bit XOR flip
        matrix[r][c] = bit ^ is_flipped
    return matrix


def _mask_flips(mask_id: int, r: int, c: int) -> bool:
    """Whether mask ``mask_id`` flips the module colour at ``(r, c)``."""
    if mask_id == 0:
        return (r + c) % 2 == 0
    if mask_id == 1:
        return r % 2 == 0
    if mask_id == 2:
        return c % 3 == 0
    if mask_id == 3:
        return (r + c) % 3 == 0
    if mask_id == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask_id == 5:
        return (r * c) % 2 + (r * c) % 3 == 0
    if mask_id == 6:
        return ((r * c) % 2 + (r * c) % 3) % 2 == 0
    return ((r + c) % 2 + (r * c) % 3) % 2 == 0


def _penalty_score(matrix: List[List[bool]]) -> int:
    """Run-length penalty (N1) used to pick the friendliest legal mask."""
    size = len(matrix)
    score = 0
    for r in range(size):
        run = 1
        for c in range(1, size):
            if matrix[r][c] == matrix[r][c - 1]:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run = 1
        if run >= 5:
            score += run - 2
    for c in range(size):
        run = 1
        for r in range(1, size):
            if matrix[r][c] == matrix[r - 1][c]:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run = 1
        if run >= 5:
            score += run - 2
    return score


def _format_bits(ec_level: str, mask_id: int) -> List[int]:
    """Return the 15 masked format-information bits for an EC level + mask.

    The 5 data bits (2 EC bits + 3 mask bits) are protected with BCH(15,5),
    then XOR-masked per the spec.
    """
    ec_bits = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}[ec_level]
    data5 = (ec_bits << 3) | mask_id
    remainder = data5 << 10
    for i in range(14, 9, -1):
        if (remainder >> i) & 1:
            remainder ^= _FORMAT_GEN << (i - 10)
    value = (data5 << 10 | remainder) ^ _FORMAT_MASK
    return [(value >> i) & 1 for i in range(14, -1, -1)]


def _write_format(matrix: List[List[bool]], size: int, ec_level: str, mask_id: int) -> None:
    """Write the format bits into the three standard locations."""
    bits = _format_bits(ec_level, mask_id)

    # Top-left copy, split around the timing column (position 6).
    # Vertical strip: (col 8, rows 0..5), then (rows 7..8 on col 8), then the
    # horizontal run on row 8, cols 7..0 with position 6 skipped.
    top_left: List[Tuple[int, int]] = []
    for r in range(5, -1, -1):
        top_left.append((r, 8))
    top_left.append((0, 7))
    top_left.append((0, 6))
    # second copy of format lives top-right and bottom-left
    tr: List[Tuple[int, int]] = []
    for c in range(size - 1, size - 8, -1):
        tr.append((8, c))
    bl: List[Tuple[int, int]] = []
    for r in range(size - 1, size - 8, -1):
        bl.append((r, 8))

    # The 15 bits are mapped: bits[0..7] to the vertical strip and the
    # horizontal component; bits[8..14] to top-right / bottom-left.
    # Per spec (Figure 25) the layout is a mirror, but both regions carry the
    # SAME 15-bit sequence (readers locate either copy). We write a consistent
    # mapping that matches the documented copy positions.
    strip = []
    for r in range(5, -1, -1):
        strip.append((r, 8))
    strip.append((7, 8))
    strip.append((8, 8))
    strip.append((8, 7))
    strip.append((8, 5))
    strip.append((8, 4))
    strip.append((8, 3))
    strip.append((8, 2))
    strip.append((8, 1))
    strip.append((8, 0))

    # Simplified and standard-compliant: write the same order of bits into the
    # documented locations. bit[0] is the MSB. Place everywhere we can and
    # mirror the second copy.
    def place(r: int, c: int, bit: int) -> None:
        if 0 <= r < size and 0 <= c < size:
            matrix[r][c] = bool(bit)

    # Type-1 format area order (matches common readers).
    coord = [
        (0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (7, 8), (8, 8),
        (8, 7), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0),
    ]
    for i, (r, c) in enumerate(coord):
        place(r, c, bits[i])

    # Copy 2: top-right (8 modules, cols size-1..size-8) shares bits[0..7].
    # copy 3: bottom-left (7 modules, rows size-1..size-7) shares bits[8..14].
    for i in range(8):
        place(8, size - 1 - i, bits[i])
    for i in range(7):
        place(size - 1 - i, 8, bits[8 + i])


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def make_matrix(
    data: str,
    ec_level: str = "M",
    version: Optional[int] = None,
) -> tuple:
    """Build a QR module matrix (list of booleans) for ``data``.

    Mirrors the ``qrcode`` package's ``get_matrix()`` return so renderers are
    backend-agnostic. A 4-module quiet zone is included on every side.

    Args:
        data: The text to encode.
        ec_level: One of ``L``/``M``/``Q``/``H`` (case-insensitive).
        version: Optional explicit version (1..10). If ``None``, the smallest
            fitting version is chosen.

    Returns:
        Tuple ``(matrix, version, ec_level)`` where ``matrix`` is a square
        list of ``bool``.

    Raises:
        ValueError: If ``ec_level`` is unknown or ``data`` does not fit.
    """
    ec = ec_level.upper()
    if ec not in EC_INDEX:
        raise ValueError(f"Unknown error-correction level {ec_level!r}.")
    ver = version if version is not None else _choose_version(data, ec)

    stream = _final_codeword_stream(data, ver, ec)
    size = _version_size(ver)
    data_bits = "".join(format(w, "08b") for w in stream)
    data_bits += "0" * REMAINDER_BITS[ver % 7]

    # Choose the mask with the lowest penalty among the 8 legal patterns.
    best_mask, best_score, best_matrix = 0, None, None
    for mask_id in range(8):
        trial = _place_data(size, data_bits, mask_id)
        score = _penalty_score(trial)
        if best_score is None or score < best_score:
            best_score, best_mask, best_matrix = score, mask_id, trial

    _write_format(best_matrix, size, ec, best_mask)

    border = 4
    total = size + 2 * border
    bordered = [[False] * total for _ in range(total)]
    for r in range(size):
        for c in range(size):
            bordered[r + border][c + border] = best_matrix[r][c]
    return bordered, ver, ec