"""Flask-Login User model + pydantic LoginForm for illumio-ops admin auth.

Single-admin model: the web_gui.username / password in config.json
defines the one admin user. flask-login's user_loader returns this user
if the session's user_id matches the configured username.
"""
from __future__ import annotations

from flask_login import UserMixin
from pydantic import BaseModel, Field, model_validator

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


class PasswordChangeForm(BaseModel):
    """Server-side validation for password change requests."""
    old_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=12, max_length=512)
    confirm_password: str = Field(min_length=12, max_length=512)

    @model_validator(mode='after')
    def passwords_match(self) -> 'PasswordChangeForm':
        if self.new_password != self.confirm_password:
            raise ValueError('Passwords do not match')
        return self
