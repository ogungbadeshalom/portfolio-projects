"""Email Newsletter Service.

A full-featured newsletter app: subscribe, manage subscribers, compose and send
campaigns, and track opens / clicks / unsubscribes (CAN-SPAM friendly).

Public package entry points:

- ``newsletter.main:app``  -- the FastAPI application
- ``newsletter.cli:main``  -- the ``newsletter`` Click command group
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

# Absolute path to the SQLite database that hosts every subscriber, campaign and
# send event. Overridable via NEWSLETTER_DB_URL. Importing the package must stay
# side-effect free (no database bootstrap, no FastAPI import) so that config.py
# and cli.py can import it without triggering circular imports.
_PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_URL_DEFAULT = f"sqlite:///{_PROJECT_DIR / 'newsletter.db'}"