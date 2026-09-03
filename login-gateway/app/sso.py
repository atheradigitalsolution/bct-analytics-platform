"""Contract 07 / brief 08 — the SSO handoff into Odoo.

WHY A TICKET AND NOT A SHARED COOKIE. The obvious way to let `odoo.<domain>` know who the visitor
is would be to widen the session cookie to `Domain=.<domain>`. That was refused by the Lead: a
domain-wide cookie is readable by every subdomain that exists now and every subdomain added in a
hurry later, so one XSS anywhere on the domain becomes a session takeover everywhere. A ticket is
a one-shot, 60-second, audience-scoped credential that is useless the moment it is spent.

WHY SINGLE USE IS ENFORCED HERE AND NOT IN ODOO. Odoo runs multiple workers with no shared place
to record "this ticket was already spent". The gateway is one process with one store, so this is
the only side that can answer the question honestly.

THE ROUTE TOKEN IS NOT A SESSION. It carries a database name and nothing else, and it exists for
exactly one reason: Caddy has to rewrite the Host header before Odoo sees the request, and it
cannot read Odoo's session cookie to work out which database to name. Signing it is what stops a
visitor editing a cookie to reach another tenant's login page -- the enumeration that the "tenants
get no public DNS" decision was protecting.
"""

from __future__ import annotations

import secrets
import threading
import time

import jwt

#: Ticket lifetime. Long enough for a redirect, short enough that a ticket in a log or a Referer
#: header is worthless by the time anyone reads it.
TICKET_TTL = 60

#: Audiences. Distinct from the portal's audience so an access token can never be replayed as a
#: ticket, or the reverse: `aud` is checked exactly.
TICKET_AUDIENCE = "athera-odoo-sso"
ROUTE_AUDIENCE = "athera-odoo-route"

#: A route token outlives the ticket because it is spent on every request for the whole visit.
#: It is NOT an entitlement: the gate re-reads the control plane each time it is presented.
ROUTE_TTL = 43200


class SpentTickets:
    """Tickets already exchanged. Single use is the whole security property."""

    def __init__(self) -> None:
        self._seen = {}
        self._lock = threading.Lock()

    def spend(self, jti: str, expires_at: int) -> bool:
        """True if this is the first time `jti` is spent. False on any replay."""
        now = int(time.time())
        with self._lock:
            # Opportunistic sweep. The store only ever holds tickets younger than TICKET_TTL, so
            # it cannot grow: an unbounded set keyed by an attacker-triggerable value would be a
            # memory-exhaustion vector rather than a security control.
            for spent, exp in [(k, v) for k, v in self._seen.items() if v < now]:
                del self._seen[spent]
            if jti in self._seen:
                return False
            self._seen[jti] = expires_at
            return True


def mint_ticket(settings, ring, db: str, uid: int, is_super_admin: bool) -> str:
    """`is_super_admin` is decided at issue time, where the password is available to ask Odoo.

    The exchange has no password and cannot re-derive it, so carrying it signed inside the ticket
    is the only honest option: the alternative is the exchange guessing, and a guess in this
    position either locks the super admin out or opens the door for everyone.
    """
    now = int(time.time())
    key = ring.active
    return jwt.encode(
        {
            "iss": settings.issuer,
            "aud": TICKET_AUDIENCE,
            "sub": "odoo:%s:%d" % (db, uid),
            "db": db,
            "odoo_uid": uid,
            "sa": bool(is_super_admin),
            "jti": secrets.token_urlsafe(18),
            "iat": now,
            "exp": now + TICKET_TTL,
        },
        key.private_pem,
        algorithm="RS256",
        headers={"kid": key.kid, "typ": "JWT"},
    )


def mint_route_token(settings, ring, db: str, uid: int, is_super_admin: bool) -> str:
    """`is_super_admin` travels IN the token because the routing gate has no other way to learn it.

    The gate runs on every request with no password and no Odoo call available, so it cannot
    re-derive the flag. Signing it means a visitor cannot grant it to themselves, and the flag only
    ever widens the door for the account it was minted for.
    """
    now = int(time.time())
    key = ring.active
    return jwt.encode(
        {
            "iss": settings.issuer,
            "aud": ROUTE_AUDIENCE,
            "db": db,
            "odoo_uid": uid,
            "sa": bool(is_super_admin),
            "iat": now,
            "exp": now + ROUTE_TTL,
        },
        key.private_pem,
        algorithm="RS256",
        headers={"kid": key.kid, "typ": "JWT"},
    )


def _verify(settings, ring, token: str, audience: str) -> dict:
    """Verify against every key in the ring, algorithm pinned to RS256.

    Trying each key rather than reading `kid` and trusting it keeps rotation working without
    letting the token choose which key validates it.
    """
    last = None
    # `ring.keys` is a MAPPING of kid -> SigningKey, not a list. Iterating it directly yields kid
    # strings and every verification fails with an attribute error that the caller reports as
    # "invalid ticket" — a wrong-looking security refusal caused by a wrong-looking loop.
    for key in ring.keys.values():
        try:
            return jwt.decode(
                token,
                key.public,
                algorithms=["RS256"],
                audience=audience,
                issuer=settings.issuer,
                leeway=5,
            )
        except Exception as exc:  # noqa: BLE001 - the last failure is reported, never raised here
            last = exc
    raise ValueError(str(last) if last else "no verification key")


def verify_ticket(settings, ring, token: str) -> dict:
    return _verify(settings, ring, token, TICKET_AUDIENCE)


def verify_route_token(settings, ring, token: str) -> dict:
    return _verify(settings, ring, token, ROUTE_AUDIENCE)


def entitled_to_odoo(claims: dict, entitlement) -> bool:
    """Contract 07's gate for the Odoo door, plus the super-admin bypass.

    The bypass is not a convenience. `athera_admin` has no row in `tenant_registry.tenants`, so
    `is_active()` is false for it forever; without this, turning the gate on would lock the super
    admin out of the console the gate is meant to protect. `hub-portal` already gates on
    `is_super_admin` rather than on the subscription for exactly this reason.
    """
    if bool(claims.get("is_super_admin", False)):
        return True
    return bool(entitlement.active) and "odoo" in tuple(entitlement.products)
