"""
href_utils.py — Canonical helpers for parsing Illumio PCE HREF strings.

An Illumio href looks like: /orgs/1/workloads/abc123
The last path segment is the resource ID.
"""


def extract_id(href: str) -> str:
    """Return the last path segment of an Illumio PCE href string.

    Examples::

        >>> extract_id("/orgs/1/workloads/abc123")
        'abc123'
        >>> extract_id("/orgs/1/rule_sets/42/sec_rules/7")
        '7'
        >>> extract_id("")
        ''
        >>> extract_id(None)
        ''

    Args:
        href: An Illumio PCE href string, or None/empty.

    Returns:
        The last path segment, or an empty string if href is falsy.
    """
    return href.split("/")[-1] if href else ""
