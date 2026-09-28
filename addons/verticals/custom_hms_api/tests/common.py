# -*- coding: utf-8 -*-
"""Shared helpers for the API boundary tests."""
import secrets


def fixture_password():
    """A throwaway login secret for a test user, minted at run time.

    Written literally, this line reads exactly like a leaked credential to
    ``scripts/scan-secrets.py`` -- and it is right to say so: a scanner
    cannot tell an invented fixture from a real password, and teaching it
    the difference means widening a pattern that exists to catch the real
    thing. A gate that goes red on harmless findings is a gate people learn
    to wave through, so the fixture moves instead of the rule.

    Generating it also removes a shared constant that two test modules would
    otherwise have to keep in step.
    """
    return secrets.token_urlsafe(12)
