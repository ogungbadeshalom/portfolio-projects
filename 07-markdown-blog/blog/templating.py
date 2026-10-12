"""Template loading & rendering (Jinja2 preferred, built-in fallback).

The :mod:`blog.templating` module provides a small :class:`TemplateEngine` that
renders HTML/XML pages from a template directory.

When **Jinja2** is importable it is used with ``autoescape`` enabled, giving
full control-flow templates.  Otherwise a compact string-substitution renderer
handles the handful of placeholder patterns the bundled templates rely on:

* ``{{ variable }}``                  -- escaped interpolation
* ``{{ post.body_html|safe }}``       -- raw (already-generated) interpolation
* ``{% for x in xs %}...{% endfor %}`` -- simple repetition
* ``{% if cond %}...{% else %}...{% endif %}``
* ``{% include "name" %}``            -- inline another template

This keeps ``blog build`` working on a minimal Python install while remaining
fully compatible with the (recommended) Jinja2 provider.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

# --------------------------------------------------------------------------- #
# Expression resolution (fallback templates only)
# --------------------------------------------------------------------------- #


def _attr(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    if isinstance(value, (list, tuple, str)) and name.isdigit():
        try:
            return value[int(name)]
        except (IndexError, ValueError):
            return None
    try:
        attr = getattr(value, name)
    except AttributeError:
        return None
    return attr() if callable(attr) else attr


def _resolve_accessors(expr: str, ctx: Mapping[str, Any]) -> Any:
    """Resolve ``a.b.c`` / ``a['b']`` style expressions against ``ctx``."""
    expr = expr.strip()
    tokens = re.findall(r"[A-Za-z0-9_]+|\.[A-Za-z0-9_]+|\[[^\]]+\]", expr)
    if not tokens:
        return None
    value: Any = ctx
    for token in tokens:
        if token.startswith("."):
            value = _attr(value, token[1:])
        elif token.startswith("["):
            idx = token[1:-1].strip()
            if isinstance(value, Mapping):
                value = value.get(idx)
            elif isinstance(value, (list, tuple, str)) and idx.isdigit():
                try:
                    value = value[int(idx)]
                except (IndexError, ValueError):
                    value = None
            else:
                value = _attr(value, idx)
        else:
            value = _attr(value, token)
    return value


def _render_var(expr: str, ctx: Mapping[str, Any]) -> str:
    """Render one ``{{ ... }}`` expression (escaped unless ``|safe`` requested)."""
    expr = expr.strip()
    safe = False
    if "|safe" in expr:
        safe = True
        expr = expr.replace("|safe", "").strip()
    if expr.startswith('"') and expr.endswith('"'):
        value: Any = expr[1:-1]
    else:
        value = _resolve_accessors(expr, ctx)
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(v) for v in value)
    text = str(value)
    return text if safe else _html.escape(text)


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value != "" and value.lower() not in ("false", "no", "0", "none")
    if isinstance(value, Iterable):
        return len(list(value)) > 0  # type: ignore[arg-type]
    return bool(value)


def _eval_condition(expr: str, ctx: Mapping[str, Any]) -> bool:
    """Evaluate a simple boolean expression for ``{% if ... %}``."""
    expr = expr.strip()
    if not expr:
        return True
    if expr.startswith("not "):
        return not _truthy(_eval_condition(expr[4:].strip(), ctx))
    if " or " in expr:
        return any(_eval_condition(p, ctx) for p in expr.split(" or "))
    if " and " in expr:
        return all(_eval_condition(p, ctx) for p in expr.split(" and "))
    for operator in ("!=", "==", "<=", ">=", "<", ">"):
        if operator in expr:
            lhs_txt, _, rhs_txt = expr.partition(operator)
            lhs = _resolve_accessors(lhs_txt, ctx)
            if rhs_txt.strip() == "None":
                rhs: Any = None
            elif rhs_txt.strip() in ("'", '"'):
                rhs = ""
            else:
                rhs = _resolve_accessors(rhs_txt, ctx)
            if operator == "!=":
                return lhs != rhs
            if operator == "==":
                return lhs == rhs
            return False  # ordering: not needed by bundled templates
    return _truthy(_resolve_accessors(expr, ctx))


def _render_fallback(source: str, ctx: Mapping[str, Any], loader: "Optional[FallbackLoader]") -> str:
    """Render fallback-template ``source`` against ``ctx``."""
    out: List[str] = []
    i, n = 0, len(source)
    while i < n:
        if source.startswith("{{", i):
            end = source.find("}}", i + 2)
            if end == -1:
                out.append(source[i:])
                break
            out.append(_render_var(source[i + 2 : end], ctx))
            i = end + 2
            continue
        if source.startswith("{%", i):
            end = source.find("%}", i + 2)
            if end == -1:
                out.append(source[i:])
                break
            tag = source[i + 2 : end].strip()
            i = end + 2
            parts = tag.split(maxsplit=1)
            keyword = parts[0]
            rest = parts[1].strip() if len(parts) > 1 else ""

            if keyword == "for":
                var, _, it_expr = rest.partition(" in ")
                block_end = source.find("{% endfor %}", i)
                if block_end == -1:
                    continue
                inner = source[i:block_end]
                items = _resolve_accessors(it_expr.strip(), ctx)
                if items is None:
                    items = []
                seq = list(items) if isinstance(items, (list, tuple)) else list(items)
                for index, item in enumerate(seq):
                    sub_ctx = dict(ctx)
                    sub_ctx[var.strip()] = item
                    sub_ctx["loop"] = {"index": index + 1, "first": index == 0}
                    out.append(_render_fallback(inner, sub_ctx, loader))
                i = block_end + len("{% endfor %}")
                continue

            if keyword == "if":
                block_end = source.find("{% endif %}", i)
                if block_end == -1:
                    continue
                # find {% else %} within
                else_pos = source.find("{% else %}", i)
                if else_pos != -1 and else_pos < block_end:
                    then_body = source[i:else_pos]
                    else_body = source[else_pos + len("{% else %}"):block_end]
                    chosen = then_body if _eval_condition(rest, ctx) else else_body
                else:
                    chosen = source[i:block_end] if _eval_condition(rest, ctx) else ""
                out.append(_render_fallback(chosen, ctx, loader) if chosen else "")
                i = block_end + len("{% endif %}")
                continue

            if keyword == "include":
                fname = rest.strip().strip("'\"")
                if loader is not None and fname:
                    try:
                        out.append(_render_fallback(loader.read(fname), dict(ctx), loader))
                    except FileNotFoundError:
                        out.append(f"<!-- missing template: {fname} -->")
                continue

            # Unknown/ignored tags (block/extends handled by the template).
            continue

        out.append(source[i])
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------- #
# Fallback template + loader
# --------------------------------------------------------------------------- #


class FallbackTemplate:
    """A minimal Jinja2-like template backed by a :class:`FallbackLoader`."""

    def __init__(self, source: str, loader: "FallbackLoader") -> None:
        self._source = source
        self._loader = loader
        self._blocks: Dict[str, str] = {}
        self._extend: Optional[str] = None
        self._parse()

    def _parse(self) -> None:
        """Find ``{% extends %}`` and extract ``{% block %}/{% endblock %}``."""
        for m in re.finditer(r"\{%\s*extends\s+([\"'])([^\"']+)\1\s*%\}", self._source):
            self._extend = m.group(2)
        for m in re.finditer(r"\{%\s*block\s+(\w+)\s*%\}(.*?)\{%\s*endblock(?:\s+\w+)?\s*%\}", self._source, flags=re.S):
            self._blocks[m.group(1)] = m.group(2)

    def render(self, **kwargs: Any) -> str:
        ctx: Dict[str, Any] = dict(kwargs)
        body = self._source
        # Strip the extends / block definition tags from the output body.
        body = re.sub(r"\{%\s*extends\s+[\"'][^\"']+[\"']\s*%\}|\{%\s*block\s+\w+\s*%\}|\{%\s*endblock(?:\s+\w+)?\s*%\}", "", body)
        rendered = _render_fallback(body, ctx, self._loader)
        if self._extend and self._loader is not None:
            try:
                base = self._loader.get(self._extend)
                rendered = base.render_with_blocks(self._blocks, ctx)
            except FileNotFoundError:
                pass
        return rendered

    def render_with_blocks(self, blocks: Mapping[str, str], ctx: Mapping[str, Any]) -> str:
        """Render this template as a base, substituting the given ``blocks``.

        Child blocks replace any ``{% block name %}` section of the base via
        the bundled ``{% block %}`` mechanism exposed through ``ctx``.
        """
        fallback_blocks = dict(blocks)
        # Render normally but let each block in the base be filled by the
        # overridden block body where a matching name exists.
        def fill(m: "re.Match") -> str:
            name = m.group(1)
            if name in fallback_blocks:
                return _render_fallback(fallback_blocks[name], ctx, self._loader)
            return _render_fallback(m.group(2), ctx, self._loader)

        body = re.sub(
            r"\{%\s*block\s+(\w+)\s*%\}(.*?)\{%\s*endblock(?:\s+\w+)?\s*%\}",
            fill,
            self._source,
            flags=re.S,
        )
        body = re.sub(r"\{%\s*extends\s+[\"'][^\"']+[\"']\s*%\}", "", body)
        return _render_fallback(body, ctx, self._loader)


class FallbackLoader:
    """Load fallback templates from a directory."""

    def __init__(self, templates_dir: Optional[Path]) -> None:
        self.templates_dir = templates_dir

    def read(self, name: str) -> str:
        if self.templates_dir is None:
            raise FileNotFoundError(name)
        path = self.templates_dir / name
        if not path.is_file():
            raise FileNotFoundError(name)
        return path.read_text(encoding="utf-8")

    def get(self, name: str) -> FallbackTemplate:
        return FallbackTemplate(self.read(name), self)


# --------------------------------------------------------------------------- #
# Public engine
# --------------------------------------------------------------------------- #

class TemplateEngine:
    """Thin facade over Jinja2 (preferred) or the built-in fallback.

    Parameters
    ----------
    templates_dir:
        Directory containing the ``*.html`` / ``*.xml`` templates.
    """

    def __init__(self, templates_dir: Path) -> None:
        self.templates_dir = templates_dir
        self._env = None
        self._loader: Optional[FallbackLoader] = None
        if self._try_jinja():
            return
        self._loader = FallbackLoader(templates_dir)

    def _try_jinja(self) -> bool:
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape  # type: ignore

            env = Environment(
                loader=FileSystemLoader(str(self.templates_dir)),
                autoescape=select_autoescape(default_for_string=True, default=True),
                trim_blocks=True,
                lstrip_blocks=True,
            )
            env.filters.setdefault("slugify", lambda s: s)
            env.globals.setdefault("ordinal", _ordinal)
            self._env = env
            return True
        except ImportError:
            self._env = None
            return False

    def get_template(self, name: str):
        if self._env is not None:
            return self._env.get_template(name)
        return self._loader.get(name)

    def render(self, name: str, **context: Any) -> str:
        return self.get_template(name).render(**context)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"