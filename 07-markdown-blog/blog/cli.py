"""Command-line interface for the blog generator.

Provides the ``blog`` console command:

* ``blog init ./my-blog``  -- scaffold a new blog root
* ``blog new "Title" --tags python`` -- create a fresh post
* ``blog build``          -- generate ``dist/``
* ``blog serve``          -- local preview at :8000 (with auto-rebuild)
* ``blog deploy``         -- push ``dist/`` to a git remote (GitHub Pages)

Uses ``click`` when available, otherwise falls back to a tiny argparse shim so
the CLI stays usable on a minimal install.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

try:  # pragma: no cover - exercised only on a minimal install
    import click
except Exception:  # pragma: no cover
    click = None  # type: ignore[assignment]

from . import builder
from .config import SiteConfig

# Path of the bundled templates/static skeletons inside this package.
_PKG_DIR = Path(__file__).resolve().parent
_BUNDLED_TEMPLATES = _PKG_DIR / "templates"
_BUNDLED_STATIC = _PKG_DIR / "static"

_INDEX_TEMPLATE_FILENAME = "index.html"


# --------------------------------------------------------------------------- #
# Click entrypoint (preferred)
# --------------------------------------------------------------------------- #


def _make_click_group() -> "click.Group":
    @click.group()
    @click.version_option(package_name="markdown-blog")
    def main() -> None:
        """A tiny static Markdown blog generator (RSS, sitemap, OG images)."""

    @main.command()
    @click.argument("path", type=click.Path(path_type=Path), default=".")
    @click.option("--title", default=None, help="Blog title.")
    def init(path: Path, title: Optional[str]) -> None:
        """Scaffold a new blog site rooted at PATH."""
        init_blog(path, title=title)

    @main.command()
    @click.argument("title")
    @click.option("--tags", default="", help="Comma-separated tags.")
    @click.option("--author", default=None, help="Post author.")
    @click.option("--draft", is_flag=True, default=False, help="Mark post as a draft.")
    def new(title: str, tags: str, author: Optional[str], draft: bool) -> None:
        """Create a new post with TITLE in the current blog."""
        new_post(
            Path("."),
            title,
            tags=[t.strip() for t in tags.split(",") if t.strip()],
            author=author,
            draft=draft,
        )

    @main.command()
    @click.option("--drafts", is_flag=True, default=False, help="Include draft posts.")
    @click.option("--no-og", is_flag=True, default=False, help="Skip OG images.")
    def build(drafts: bool, no_og: bool) -> None:
        """Build the current blog into ``dist/``."""
        counts = builder.build(
            Path("."),
            include_drafts=drafts,
            generate_og=not no_og,
            quiet=False,
        )
        _print_build_summary(counts)

    @main.command()
    @click.option("--host", default="127.0.0.1", help="Interface to bind.")
    @click.option("--port", default=8000, type=int, help="Port to serve on.")
    @click.option("--drafts", is_flag=True, default=False, help="Preview drafts.")
    @click.option("--no-watch", is_flag=True, default=False, help="Disable auto-rebuild.")
    def serve(host: str, port: int, drafts: bool, no_watch: bool) -> None:
        """Serve the built site locally (auto-rebuilds on change)."""
        serve_blog(
            Path("."),
            host=host,
            port=port,
            include_drafts=drafts,
            watch=not no_watch,
        )

    @main.command()
    @click.option("--remote", default="origin", help="Git remote to push to.")
    @click.option("--branch", default="gh-pages", help="Branch to push dist/ to.")
    @click.option("--message", default=None, help="Commit message.")
    def deploy(remote: str, branch: str, message: Optional[str]) -> None:
        """Publish ``dist/`` to a git remote (e.g. GitHub Pages)."""
        deploy_blog(Path("."), remote=remote, branch=branch, message=message)

    return main


# --------------------------------------------------------------------------- #
# Shareable implementations (called by both Click and argparse paths)
# --------------------------------------------------------------------------- #


def init_blog(root: Path, title: Optional[str] = None) -> None:
    """Scaffold a new blog site root with posts/templates/static/settings."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    posts_dir = root / "posts"
    templates_dir = root / "templates"
    static_dir = root / "static"
    posts_dir.mkdir(exist_ok=True)
    templates_dir.mkdir(exist_ok=True)
    static_dir.mkdir(exist_ok=True)

    # Settings file.
    cfg_path = root / "settings.cfg"
    cfg = SiteConfig(site_url=f"https://examples.example/{root.name}")
    if title:
        cfg.title = title
    if not cfg_path.exists():
        cfg.save(cfg_path)

    # Default templates.
    if _BUNDLED_TEMPLATES.is_dir():
        _copy_dir(_BUNDLED_TEMPLATES, templates_dir)
    else:  # pragma: no cover - skeleton always ships in this repo
        _write_default_templates(templates_dir)

    # Default static assets.
    if _BUNDLED_STATIC.is_dir():
        _copy_dir(_BUNDLED_STATIC, static_dir)

    # A sample post so the site builds out of the box.
    sample = posts_dir / "welcome.md"
    if not sample.exists():
        sample.write_text(
            "---\n"
            "title: Welcome\n"
            "date: %s\n"
            "author: %s\n"
            "tags: [hello]\n"
            "description: Your first post.\n"
            "---\n\n"
            "This site is generated from Markdown with the `blog` tool.\n"
            % (date.today().isoformat(), cfg.author),
            encoding="utf-8",
        )

    print(f"Initialized blog in {root.resolve()}")
    print(f"  posts/       content (Markdown)")
    print(f"  templates/   Jinja2 HTML templates")
    print(f"  static/      CSS / images copied into dist/assets/")
    print(f"  settings.cfg site metadata")
    print("Next:  blog new \"My first post\" && blog build")


def new_post(
    root: Path,
    title: str,
    tags: Optional[List[str]] = None,
    author: Optional[str] = None,
    draft: bool = False,
) -> Path:
    """Create one new Markdown post and return its path."""
    root = Path(root)
    posts_dir = root / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)
    cfg = SiteConfig.from_file(root / "settings.cfg")

    slug = _slug(title)
    path = posts_dir / f"{slug}.md"
    if path.exists():
        raise FileExistsError(f"post already exists: {path}")

    tag_line = ", ".join(tags or [])
    draft_flag = "true" if draft else "false"
    frontmatter = [
        "---",
        f"title: {title}",
        f"date: {date.today().isoformat()}",
        f"author: {author or cfg.author}",
        f"tags: [{tag_line}]" if tag_line else "tags: []",
        f"draft: {draft_flag}",
        f"description: A new post about {title}.",
        "---",
        "",
        f"# {title}",
        "",
        "Write your content here in Markdown.",
        "",
    ]
    path.write_text("\n".join(frontmatter), encoding="utf-8")
    print(f"Created {path}")

    if draft:
        print("(marked as draft: excluded from production `blog build`)")
    return path


def serve_blog(
    root: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
    include_drafts: bool = False,
    watch: bool = True,
) -> None:
    """Build (if needed) and serve ``dist/``, optionally auto-rebuilding."""
    try:
        from .serve import make_server, url_for
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Could not start server: {exc}")
        sys.exit(1)

    server = make_server(host, port, root, include_drafts=include_drafts, rebuild_on_change=watch)
    display = url_for(server)
    print(f"Serving {root.resolve() / 'dist'}")
    print(f"  -> {display}")
    if watch:
        print("  auto-rebuild: on (watching posts/ and static/)")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\nStopped.")
    finally:
        server.shutdown()


def deploy_blog(
    root: Path,
    remote: str = "origin",
    branch: str = "gh-pages",
    message: Optional[str] = None,
) -> None:
    """Commit ``dist/`` to a git branch and push it to ``remote``.

    Works with GitHub Pages-style hosting: the site lives in a ``gh-pages``
    branch.  If the project has no git repo yet, we initialise one.
    """
    root = Path(root)
    build_dir = root / "dist"
    if not build_dir.is_dir():
        print("Nothing to deploy yet: run `blog build` first." )
        return

    if not shutil.which("git"):
        print("Error: `git` is not on PATH; cannot deploy.")
        sys.exit(1)

    repo = _ensure_git_repo(root)
    _gh_pages_root(repo, build_dir)

    commit_msg = message or f"Deploy blog build {datetime.now().isoformat(timespec='seconds')}"

    # Root-level commits (orphan branch) keep dist/ at the top so URLs match.
    _checkout_orphan(repo, branch)
    _stage_and_commit(repo, commit_msg)
    _push(repo, remote, branch)


def _ensure_git_repo(root: Path) -> Path:
    repo = root.resolve()
    if not (repo / ".git").exists():
        print(f"Initialising git repo at {repo}")
        _run_git(repo, "init", "-q")
        _run_git(repo, "config", "user.email", "blog@example.com")
        _run_git(repo, "config", "user.name", "blog-deploy")
    return repo


def _gh_pages_root(repo: Path, dist_dir: Path) -> None:
    """Place ``dist/*`` at the repo root (for orphaned gh-pages branch)."""
    # Remove tracked files then copy the fresh build on top.
    for child in repo.iterdir():
        if child.name in {".git", "dist"} or child.is_dir() and child.name.startswith("."):
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for item in dist_dir.iterdir():
        dest = repo / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)


def _checkout_orphan(repo: Path, branch: str) -> None:
    _run_git(repo, "checkout", "--orphan", branch)
    _run_git(repo, "rm", "-rf", "--cached", ".", "-q", check=False)


def _stage_and_commit(repo: Path, message: str) -> None:
    _run_git(repo, "add", "-A")
    # Only commit if there are staged changes.
    status = _run_git(repo, "status", "--porcelain", check=False)
    if isinstance(status, bytes):
        status = status.decode("utf-8", "replace")
    if status and status.strip():
        _run_git(repo, "commit", "-q", "-m", message)
        print(f"Committed build: {message}")
    else:
        print("No changes to commit.")


def _push(repo: Path, remote: str, branch: str) -> None:
    remotes = _run_git(repo, "remote", check=False)
    if isinstance(remotes, bytes):
        remotes = remotes.decode("utf-8", "replace")
    if remote not in (remotes or ""):
        print(f"Remote {remote!r} not configured; skipping push (add it with `git remote add`).")
        return
    _run_git(repo, "push", remote, branch)
    print(f"Pushed {branch} -> {remote}")


def _run_git(root: Path, *args: str, check: bool = True) -> Optional[bytes]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and proc.returncode != 0:
        print("[git] " + (proc.stdout or b"").decode("utf-8", "replace").strip())
        sys.exit(proc.returncode)
    return proc.stdout


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _slug(title: str) -> str:
    from .parser import slugify

    return slugify(title)


def _copy_dir(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        dest = dst / item.name
        if not dest.exists():
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)


def _write_default_templates(templates_dir: Path) -> None:  # pragma: no cover
    """Fallback: write a minimal handful of templates if the bundle is absent."""
    (templates_dir / "base.html").write_text(
        "<!DOCTYPE html><html><head><title>{{ config.title }}</title></head>"
        "<body><main>{% block content %}{% endblock %}</main></body></html>",
        encoding="utf-8",
    )
    (templates_dir / "index.html").write_text(
        "{% extends \"base.html\" %}{% block content %}"
        "{% for post in posts %}<h2><a href=\"{{ root }}/posts/{{ post.slug }}/\">{{ post.title }}</a></h2>"
        "{% endfor %}{% endblock %}",
        encoding="utf-8",
    )
    (templates_dir / "post.html").write_text(
        "{% extends \"base.html\" %}{% block content %}"
        "<h1>{{ post.title }}</h1>{{ post.body_html|safe }}{% endblock %}",
        encoding="utf-8",
    )
    (templates_dir / "tag.html").write_text(
        "{% extends \"index.html\" %}{% block content %}{% endblock %}",
        encoding="utf-8",
    )


def _print_build_summary(counts) -> None:
    print(
        f"Done: {counts['posts']} posts, {counts['tags']} tags, "
        f"{counts['pages']} pages, {counts['og_images']} OG images"
    )


# --------------------------------------------------------------------------- #
# Module-level entrypoint (argparse fallback)
# --------------------------------------------------------------------------- #


def _main_argparse(argv: List[str]) -> int:  # pragma: no cover - used only w/o click
    import argparse

    p = argparse.ArgumentParser(prog="blog", description="Static Markdown blog generator.")
    sub = p.add_subparsers(dest="command")

    pi = sub.add_parser("init"); pi.add_argument("path", nargs="?", default=".")
    pn = sub.add_parser("new"); pn.add_argument("title")
    pn.add_argument("--tags", default=""); pn.add_argument("--draft", action="store_true")
    pb = sub.add_parser("build"); pb.add_argument("--drafts", action="store_true")
    pb.add_argument("--no-og", action="store_true")
    ps = sub.add_parser("serve"); ps.add_argument("--host", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=8000)
    ps.add_argument("--no-watch", action="store_true")
    pd = sub.add_parser("deploy")

    args = p.parse_args(argv)
    if args.command == "init":
        init_blog(Path(args.path))
    elif args.command == "new":
        new_post(Path("."), args.title,
                 tags=[t.strip() for t in args.tags.split(",") if t.strip()],
                 draft=args.draft)
    elif args.command == "build":
        counts = builder.build(Path("."), include_drafts=args.drafts, generate_og=not args.no_og)
        _print_build_summary(counts)
    elif args.command == "serve":
        serve_blog(Path("."), host=args.host, port=args.port, watch=not args.no_watch)
    elif args.command == "deploy":
        deploy_blog(Path("."))
    else:
        p.print_help()
        return 1
    return 0


def main() -> None:
    """The ``blog`` console entry point."""
    if click is not None:
        from click.testing import CliRunner  # noqa: F401  (ensures click is fully usable)

        _make_click_group()(prog_name="blog")
        return
    _main_argparse(sys.argv[1:])  # pragma: no cover - no-click fallback


if __name__ == "__main__":  # pragma: no cover - invoked directly
    main()