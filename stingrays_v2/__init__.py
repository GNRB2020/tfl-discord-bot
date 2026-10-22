"""Stingrays v2: isolated Postgres-backed club management module."""

def register_stingrays_v2(app):
    from .api import register_stingrays_v2 as register
    return register(app)
