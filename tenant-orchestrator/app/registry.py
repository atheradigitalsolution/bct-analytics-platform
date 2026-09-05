"""Reads and writes tenant_registry. The only place this service holds state."""

from __future__ import annotations

import contextlib
import json
import logging

import psycopg2
import psycopg2.extras

logger = logging.getLogger("orchestrator.registry")

#: Columns the API returns. Explicit rather than SELECT *, so adding a column
#: to the schema does not silently start publishing it over HTTP.
TENANT_COLUMNS = (
    "id, slug, display_name, db_name, state::text AS state, plan_code, "
    "valid_until, trial_ends_at, insight_source_kind, csm_user_id, "
    "contact_email, contact_phone, backup_schedule_cron, backup_retention_daily, "
    "last_backup_at, last_backup_size_bytes, last_backup_id, features, "
    "created_at, activated_at, suspended_at, archived_at, purge_after, "
    "last_seen_at, notes"
)


class TenantNotFound(Exception):
    pass


class Registry:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextlib.contextmanager
    def _cursor(self, readonly: bool = False):
        conn = psycopg2.connect(self._dsn, connect_timeout=5)
        try:
            conn.set_session(readonly=readonly, autocommit=False)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- reads ---------------------------------------------------------
    def list_tenants(self, state: str | None = None) -> list[dict]:
        with self._cursor(readonly=True) as cur:
            if state:
                cur.execute(
                    f"SELECT {TENANT_COLUMNS} FROM tenant_registry.tenants "  # noqa: S608
                    "WHERE state = %s ORDER BY id",
                    (state,),
                )
            else:
                cur.execute(
                    f"SELECT {TENANT_COLUMNS} FROM tenant_registry.tenants ORDER BY id"  # noqa: S608
                )
            return [dict(r) for r in cur.fetchall()]

    def get_tenant(self, slug: str) -> dict:
        with self._cursor(readonly=True) as cur:
            cur.execute(
                f"SELECT {TENANT_COLUMNS} FROM tenant_registry.tenants WHERE slug = %s",  # noqa: S608
                (slug,),
            )
            row = cur.fetchone()
        if row is None:
            raise TenantNotFound(slug)
        return dict(row)

    def entitlement(self, slug: str) -> dict:
        """The same two functions the login gateway consults.

        Deliberately NOT a second implementation of "is this tenant active".
        One rule, one place; three copies of it eventually disagree, and the way
        that surfaces is a suspended client keeping a working dashboard.
        """
        with self._cursor(readonly=True) as cur:
            cur.execute(
                "SELECT tenant_registry.is_active(%s) AS active, "
                "tenant_registry.entitlements(%s) AS products",
                (slug, slug),
            )
            row = cur.fetchone()
        return {"active": bool(row["active"]), "products": list(row["products"] or [])}

    # --- writes --------------------------------------------------------
    def create_tenant(self, payload: dict) -> dict:
        """Insert the registry row.

        THE COLUMN LIST HERE IS A CONTRACT, and it was three columns short.
        `csm_user_id`, `features` and `backup_schedule_cron` exist on this table
        and are sent by the provisioning wizard on every call; the INSERT did not
        name them, so every tenant created from the console arrived with no CSM
        assigned, no backup schedule and no feature flags -- and nothing reported
        it, because dropping a key silently is exactly what a hand-rolled body
        parser does. The API layer now refuses unknown keys outright, which is
        what keeps this list and that model honest with each other.
        """
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO tenant_registry.tenants "
                "(slug, display_name, db_name, state, plan_code, valid_until, "
                " insight_source_kind, contact_email, contact_phone, "
                " csm_user_id, features, backup_schedule_cron, notes) "
                "VALUES (%(slug)s, %(display_name)s, %(db_name)s, 'provisioning', "
                "        %(plan_code)s, %(valid_until)s, %(insight_source_kind)s, "
                "        %(contact_email)s, %(contact_phone)s, "
                "        %(csm_user_id)s, %(features)s, %(backup_schedule_cron)s, "
                "        %(notes)s) "
                f"RETURNING {TENANT_COLUMNS}",  # noqa: S608
                payload,
            )
            return dict(cur.fetchone())

    def extend_validity(self, slug: str, days: int) -> dict:
        """Push `valid_until` forward by `days`, and never backward.

        GREATEST, and from the LATER of now and the current expiry. A tenant
        whose access lapsed a month ago must not receive thirty days counted from
        that lapsed date -- that would hand back an extension that has already
        expired, and the operator would have no way to tell from the response
        that nothing happened.

        A SUSPENDED TENANT STAYS SUSPENDED. Payment-driven extension resumes a
        tenant because paying the invoice removes the reason for the suspension;
        a manual grant carries no such proof. Suspension has its own reason and
        its own button, and one click must not forgive two different things.
        """
        with self._cursor() as cur:
            cur.execute(
                "UPDATE tenant_registry.tenants "
                "   SET valid_until = GREATEST(COALESCE(valid_until, now()), now()) "
                "                     + (%s || ' days')::interval "
                " WHERE slug = %s "
                f"RETURNING {TENANT_COLUMNS}",  # noqa: S608
                (days, slug),
            )
            row = cur.fetchone()
        if row is None:
            raise TenantNotFound(slug)
        return dict(row)

    def set_state(self, slug: str, state: str, stamp_column: str | None = None) -> dict:
        """Move a tenant's lifecycle state, stamping the matching timestamp.

        `state` and `stamp_column` are never caller-supplied: the routers map a
        route onto a fixed pair, so nothing user-controlled reaches this SQL.
        """
        assert state in {"provisioning", "active", "suspended", "archived", "failed"}
        assert stamp_column in {None, "activated_at", "suspended_at", "archived_at"}
        stamp = f", {stamp_column} = now()" if stamp_column else ""
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE tenant_registry.tenants SET state = %s{stamp} "  # noqa: S608
                f"WHERE slug = %s RETURNING {TENANT_COLUMNS}",
                (state, slug),
            )
            row = cur.fetchone()
        if row is None:
            raise TenantNotFound(slug)
        return dict(row)

    def log_action(
        self,
        slug: str | None,
        action: str,
        actor: str,
        outcome: str,
        detail: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Append to the hash-chained audit log.

        Never raises into the caller's path. An action that succeeded and then
        failed to be logged is still an action that succeeded, and turning it
        into a 500 would make the audit log an availability dependency of the
        thing it audits. It IS logged locally at error level, loudly.
        """
        try:
            with self._cursor() as cur:
                cur.execute(
                    "INSERT INTO tenant_registry.action_log "
                    "(tenant_id, tenant_slug, action, actor, detail, outcome, error) "
                    "VALUES ((SELECT id FROM tenant_registry.tenants WHERE slug = %s), "
                    "        %s, %s, %s, %s, %s, %s)",
                    (slug, slug, action, actor,
                     json.dumps(detail) if detail is not None else None,
                     outcome, error),
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("action_log write failed action=%s slug=%s: %s", action, slug, exc)

    def list_backups(self, slug: str, limit: int = 100) -> list[dict]:
        with self._cursor(readonly=True) as cur:
            cur.execute(
                "SELECT id, tenant_slug, kind, started_at, finished_at, size_bytes, "
                "       path, checksum_sha256, outcome, error, expires_at "
                "FROM tenant_registry.backups WHERE tenant_slug = %s "
                "ORDER BY started_at DESC LIMIT %s",
                (slug, min(int(limit), 500)),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_backup(self, backup_id: int) -> dict:
        with self._cursor(readonly=True) as cur:
            cur.execute(
                "SELECT id, tenant_slug, kind, started_at, finished_at, size_bytes, "
                "       path, checksum_sha256, outcome, error, expires_at "
                "FROM tenant_registry.backups WHERE id = %s",
                (backup_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise TenantNotFound(str(backup_id))
        return dict(row)

    def ping(self) -> bool:
        try:
            with self._cursor(readonly=True) as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() is not None
        except Exception as exc:  # noqa: BLE001
            logger.error("registry ping failed: %s", exc)
            return False
