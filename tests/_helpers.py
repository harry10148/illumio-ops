"""Shared test helpers (non-fixture)."""


def _csrf(login_response) -> str:
    """Extract CSRF token from a Flask test-client login response."""
    return (login_response.get_json() or {}).get("csrf_token", "")
