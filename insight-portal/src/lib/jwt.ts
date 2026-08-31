/**
 * JWT verification against the gateway's JWKS.
 *
 * Lives apart from `session.ts` because `middleware.ts` needs it and must not import
 * `next/headers`. Everything here is Web-Crypto only, so it runs unchanged in the edge runtime
 * middleware executes in.
 *
 * Verification rules are contract 02 / contract 06 §5, and are pinned rather than negotiated:
 *   - algorithm pinned to RS256, so `alg: none` and HS256 confusion are rejected before a key is
 *     even selected;
 *   - `iss` and `aud` checked exactly;
 *   - `exp`/`nbf` with 30 s leeway;
 *   - key selected by `kid` (two keys are published from day one so rotation needs no outage).
 */
import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";

import { config } from "./config";

/** The claim set, contract 02. */
export interface Session {
  iss: string;
  aud: string;
  sub: string;
  tenant_id: string;
  odoo_uid: number;
  roles: string[];
  /** Operating Unit ids. **An empty array means NO Operating Units, never "all".** */
  allowed_ou: number[];
  /** The explicit bypass. **Absent is `false`.** Never infer it from an empty `allowed_ou`. */
  all_ou: boolean;
  company_ids: number[];
  iat: number;
  exp: number;
}

let jwks: ReturnType<typeof createRemoteJWKSet> | null = null;

function keySet(): ReturnType<typeof createRemoteJWKSet> {
  if (jwks === null) {
    jwks = createRemoteJWKSet(new URL(config.jwksUrl), {
      cooldownDuration: 30_000,
      cacheMaxAge: 600_000,
    });
  }
  return jwks;
}

function asNumberArray(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is number => typeof entry === "number");
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === "string");
}

/**
 * Map a verified payload onto `Session`.
 *
 * The `all_ou` line is the whole point of the GATE 3 amendment: `Boolean(payload.all_ou)` makes an
 * ABSENT claim `false`. A token that predates the claim therefore grants nothing rather than
 * everything, and an empty `allowed_ou` is never read as a bypass. Getting this backwards was a
 * real privilege escalation earlier in this build.
 */
export function toSession(payload: JWTPayload): Session | null {
  const tenant = payload.tenant_id;
  if (typeof tenant !== "string" || tenant === "") return null;
  if (typeof payload.sub !== "string") return null;
  const aud = payload.aud;
  return {
    iss: typeof payload.iss === "string" ? payload.iss : "",
    aud: typeof aud === "string" ? aud : Array.isArray(aud) ? (aud[0] ?? "") : "",
    sub: payload.sub,
    tenant_id: tenant,
    odoo_uid: typeof payload.odoo_uid === "number" ? payload.odoo_uid : -1,
    roles: asStringArray(payload.roles),
    allowed_ou: asNumberArray(payload.allowed_ou),
    all_ou: payload.all_ou === true,
    company_ids: asNumberArray(payload.company_ids),
    iat: typeof payload.iat === "number" ? payload.iat : 0,
    exp: typeof payload.exp === "number" ? payload.exp : 0,
  };
}

/** Verify a bearer token. Returns `null` for every failure — the caller learns nothing else. */
export async function verifyToken(token: string | undefined): Promise<Session | null> {
  if (token === undefined || token === "") return null;
  try {
    const { payload } = await jwtVerify(token, keySet(), {
      algorithms: ["RS256"],
      issuer: config.jwtIssuer,
      audience: config.jwtAudience,
      clockTolerance: 30,
    });
    return toSession(payload);
  } catch {
    return null;
  }
}
