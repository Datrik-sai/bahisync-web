"""Vercel entrypoint: Vercel's FastAPI preset looks for `app` in index.py."""

from service.app import app  # noqa: F401
