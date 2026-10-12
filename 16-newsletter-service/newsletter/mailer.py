"""Email message construction: templates, personalization, tracking links.

Rendering and personalization live here, intentionally separate from
:mod:`newsletter.sender` (which only knows how to hand a finished message to an
SMTP backend). Benefits:

- The same builder is used by the double opt-in flow (welcome/confirm),
  unsubscribe notice, and campaign sending.
- Personalization uses the standard-library :class:`string.Template`, never
  Jinja2, so untrusted user-controlled HTML bodies (a campaign ``html_body``)
  are never executed as template code -- the spec's sandboxing requirement.

A "message" is just a small dataclass with ``from_email``, ``to_email``,
``subject``, ``html`` and ``text``. Transport backends in ``sender.py`` accept
exactly this shape, so they stay testable and swappable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from string import Template
from typing import Sequence
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, select_autoescape

from newsletter.config import settings
from newsletter.security import make_confirm_token, make_unsubscribe_token


@dataclass
class Mail:
    """A fully rendered, ready-to-send email."""

    to_email: str
    subject: str
    html: str
    text: str
    from_email: str = ""
    headers: dict = field(default_factory=dict)


class TemplateRenderer:
    """Thin wrapper over Jinja2 for the *static* (app-authored) email templates.

    Only files we control are run through Jinja -- never ``Campaign.html_body``
    (which is subscriber/user input). See :class:`Personalizer`.
    """

    def __init__(self, templates_dir: str | None = None) -> None:
        import os
        base = templates_dir or os.path.join(os.path.dirname(__file__), "templates")
        self.env = Environment(
            loader=FileSystemLoader(base),
            autoescape=select_autoescape(enabled_extensions=("html",)),
        )

    def render(self, template_name: str, **context) -> str:
        return self.env.get_template(template_name).render(**context)


class Personalizer:
    """Replaces ``$name``, ``$unsubscribe_url`` (etc.) using stdlib Template.

    Using ``string.Template`` means ``$`` followed by an identifier or brace is
    substituted against a trusted context dict; any stray ``$`` in a user
    campaign body is simply left alone (or raises on malformed ``$``), and is
    never treated as code.
    """

    _PLACEHOLDER_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")

    def render(self, template: str, *, name: str = "", unsubscribe_url: str = "", **extra) -> str:
        # Build a placeholder-value map; unused placeholders become empty-string.
        placeholders = set(self._PLACEHOLDER_RE.findall(template))
        context: dict = {"name": name, "unsubscribe_url": unsubscribe_url}
        context.update(extra)
        mapping = {key: str(context.get(key, "")) for key in placeholders}

        # Substitute below each pre-existing "$" faithfully: string.Template uses
        # "$" for substitution; escape a literal adjacent "$" only when it is
        # actually part of the pattern to keep templates honest.
        safe = template.replace("$$", "\x00")
        rendered = Template(safe).safe_substitute(mapping)
        return rendered.replace("\x00", "$")


class Mailer:
    """High-level email builder wiring templates, links, and the sender."""

    def __init__(self, renderer: TemplateRenderer | None = None) -> None:
        self.renderer = renderer or TemplateRenderer()
        self.personalizer = Personalizer()

    # --- link builders --------------------------------------------------------

    def unsubscribe_link(self, email: str, secret: str) -> str:
        token = make_unsubscribe_token(email, secret)
        return f"{settings.base_url}/api/unsubscribe?{urlencode({'token': token})}"

    def confirm_link(self, email: str, secret: str) -> str:
        token = make_confirm_token(email, secret)
        return f"{settings.base_url}/api/subscribe/confirm?{urlencode({'email': email, 'token': token})}"

    def open_pixel_url(self, campaign_id: int, subscriber_id: int) -> str:
        return f"{settings.base_url}/api/track/open/{campaign_id}?sid={subscriber_id}"

    def click_url(self, campaign_id: int, subscriber_id: int, target: str) -> str:
        q = urlencode({"target": target, "sid": subscriber_id})
        return f"{settings.base_url}/api/track/click/{campaign_id}?{q}"

    # --- message builders -----------------------------------------------------

    def confirmation(self, subscriber) -> Mail:
        """Double opt-in confirmation email (HTML + text)."""
        confirm_url = self.confirm_link(subscriber.email, subscriber.unsubscribe_token)
        context = {
            "name": subscriber.name or "",
            "confirm_url": confirm_url,
            "unsubscribe_url": self.unsubscribe_link(subscriber.email, subscriber.unsubscribe_token),
            "company": settings.company_name,
        }
        html = self.renderer.render("welcome.html", **context)
        text = self.renderer.render("welcome.txt", **context)
        return Mail(
            to_email=subscriber.email,
            subject=f"Confirm your subscription to {settings.company_name}",
            html=html,
            text=text,
            from_email=settings.from_email,
        )

    def unsubscribed_notice(self, subscriber) -> Mail:
        """Confirmation that a subscriber was removed (CAN-SPAM sends one)."""
        context = {"name": subscriber.name or "", "company": settings.company_name}
        html = self.renderer.render("unsubscribe.html", **context)
        text = self.renderer.render("unsubscribe.txt", **context)
        return Mail(
            to_email=subscriber.email,
            subject=f"You have been unsubscribed from {settings.company_name}",
            html=html,
            text=text,
            from_email=settings.from_email,
        )

    def campaign(self, campaign, subscriber, *, subscriber_id: int) -> Mail:
        """Personalized campaign email for one subscriber.

        Personalizes *both* the campaign's html_body and text_body with
        ``$name`` / ``$unsubscribe_url`` etc., and rewrites all ``http(s)``
        links in the HTML to the click-tracking redirect (keeping hrefs encoded).
        """
        unsub = self.unsubscribe_link(subscriber.email, subscriber.unsubscribe_token)
        html = self.personalizer.render(
            campaign.html_body, name=subscriber.name or "", unsubscribe_url=unsub
        )
        text = self.personalizer.render(
            campaign.text_body, name=subscriber.name or "", unsubscribe_url=unsub
        )
        # Wrap links for click tracking.
        html = self._wrap_links(html, campaign.id, subscriber_id)
        return Mail(
            to_email=subscriber.email,
            subject=campaign.subject,
            html=html,
            text=text,
            from_email=settings.from_email,
        )

    _LINK_RE = re.compile(r'(<a\b[^>]*\bhref=["\'])([^"\']+)(["\'])', re.IGNORECASE)
    _TEXT_URL_RE = re.compile(r"\bhttps?://[^\s<>\"']+")

    def _wrap_links(self, html: str, campaign_id: int, subscriber_id: int) -> str:
        """Replace every href in anchor tags with a tracking-redirect URL."""
        def _repl(m):
            href = m.group(2)
            # Don't re-wrap already-wrapped tracking links or mailto:.
            if "/api/track/click/" in href or href.lower().startswith("mailto:"):
                return m.group(0)
            wrapped = self.click_url(campaign_id, subscriber_id, href)
            return m.group(1) + wrapped + m.group(3)

        return self._LINK_RE.sub(_repl, html)

    # Expose a pure-link wrapper for tests / reuse.
    def wrap_click_urls_in_text(self, text: str, campaign_id: int, subscriber_id: int) -> str:
        def _repl(m):
            return self.click_url(campaign_id, subscriber_id, m.group(0))

        return self._TEXT_URL_RE.sub(_repl, text)