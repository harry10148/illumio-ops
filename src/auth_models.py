"""Flask-Login User model + pydantic LoginForm for illumio-ops admin auth.

Single-admin model: the web_gui.username / password_hash in config.json
defines the one admin user. flask-login's user_loader returns this user
if the session's user_id matches the configured username.
"""
from __future__ import annotations

from flask_login import UserMixin
from pydantic import BaseModel, Field


class AdminUser(UserMixin):
    """The single configured admin."""
    def __init__(self, username: str):
        self.id = username

    @classmethod
    def from_config(cls, cm):
        return cls(cm.config.get("web_gui", {}).get("username", "illumio"))


class LoginForm(BaseModel):
    """Server-side validation for /api/login payload (Phase 3 pydantic)."""
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)
