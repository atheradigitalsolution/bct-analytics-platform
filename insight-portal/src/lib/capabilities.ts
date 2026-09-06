import "server-only";

import { cacheGet, cacheKey, cacheSet } from "./cache";
import type { Session } from "./jwt";
import { query } from "./semantic";
import { VIEW_CATALOGUE, type ViewDef } from "./view";

/**
 * Which optional views this session's own data can fill.
 *
 * THE QUESTION THIS ANSWERS is "does the mart behind this view hold a single row for this
 * session", and it is asked through `/v1/query` — the same door every panel uses, with no tenant
 * argument and with the session's Operating Unit entitlement applied. There is no second data
 * path here, no SQL, and no list of tenant names.
 *
 * THE PROBE IS A GROUPED QUERY, not an aggregate. `SUM(x)` over zero rows returns one row holding
 * NULL, so an ungrouped probe cannot tell "no data" from "data summing to nothing" without the
 * portal deciding what a null total means — which is arithmetic about business meaning, and this
 * application does not do that. Adding a dimension makes the database answer instead: GROUP BY
 * over zero rows returns zero rows, and `rows.length > 0` is then a fact rather than a reading.
 *
 * THE RANGE IS DELIBERATELY UNBOUNDED. Probing over the viewer's current filter would attach a
 * view to a date window: a client whose PPOB traffic paused for the selected 30 days would lose
 * the tab and, with it, the ability to widen the range and find out why it was empty. The question
 * is "has this tenant ever done this", so the window is every date the column can hold.
 */

/** Every date `date_day` can carry. Not a guess at the data's extent — the point is to have none. */
const EVER: [string, string] = ["1000-01-01", "9999-12-31"];

/**
 * How long a capability answer is trusted, in seconds.
 *
 * Far longer than the aggregate cache's 30-second ceiling, and for a different reason. A panel's
 * TTL is bounded by the freshness the panel advertises; this is not a figure anyone reads, it is
 * whether a tab exists. Verdicts of that kind should be stable — a navigation bar that gains and
 * loses items between two clicks is worse than one that is fifteen minutes behind.
 *
 * The cost of the delay is bounded and one-directional in practice: a tenant that begins producing
 * PPOB rows waits at most this long for the tab. Nothing is hidden that was visible a moment ago
 * except when the underlying mart genuinely emptied.
 */
export const CAPABILITY_TTL_SECONDS = 900;

/** The capability verdict for one view, plus how it was reached. */
export interface Capability {
  slug: string;
  available: boolean;
  /**
   * `false` when the semantic layer did not answer and the view is being offered rather than
   * hidden. Pages use it to explain an empty view instead of asserting the client does not do this.
   */
  decided: boolean;
}

export type Capabilities = Readonly<Record<string, Capability>>;

function identityOf(session: Session) {
  return {
    sub: session.sub,
    tenant_id: session.tenant_id,
    all_ou: session.all_ou,
    allowed_ou: session.allowed_ou,
  };
}

/**
 * Probe one view.
 *
 * FAILS OPEN, and that is the interesting decision. When the semantic API does not answer, the
 * view is offered. Hiding it would turn a transient upstream failure into a dashboard that looks
 * permanently smaller, with nothing on screen saying so — the viewer would not know a tab had gone
 * missing, because a missing tab looks exactly like a tab that was never theirs. An offered view
 * whose panels then fail says what happened, in the panel, where it can be read. Nothing is
 * exposed by failing open: the view still queries under the session's own token and RLS.
 *
 * An undecided verdict is NOT cached, so the next render asks again.
 */
async function probe(session: Session, view: ViewDef): Promise<Capability> {
  const anchor = view.anchor;
  if (anchor === undefined) return { slug: view.slug, available: true, decided: true };

  const key = cacheKey(identityOf(session), "capability:" + view.slug);
  const hit = cacheGet<boolean>(key);
  if (hit !== undefined) return { slug: view.slug, available: hit, decided: true };

  const result = await query({
    metric: anchor.metric,
    dimensions: [anchor.dimension],
    filters: { date_range: EVER },
    limit: 1,
  });

  if (!result.ok) return { slug: view.slug, available: true, decided: false };

  const available = result.data.rows.length > 0;
  cacheSet(key, available, CAPABILITY_TTL_SECONDS);
  return { slug: view.slug, available, decided: true };
}

/**
 * Probe every optional view at once.
 *
 * Concurrent, and called alongside `loadOuOptions` rather than after it, so the shell waits on the
 * slowest of these rather than their sum. On a warm cache no request is made at all.
 */
export async function loadCapabilities(session: Session): Promise<Capabilities> {
  const results = await Promise.all(VIEW_CATALOGUE.map((view) => probe(session, view)));
  const out: Record<string, Capability> = {};
  for (const capability of results) out[capability.slug] = capability;
  return out;
}

/** The views to offer in the navigation, in catalogue order. */
export function visibleViews(capabilities: Capabilities): ViewDef[] {
  return VIEW_CATALOGUE.filter((view) => capabilities[view.slug]?.available !== false);
}

/**
 * The verdict for one view, for a page deciding whether to render its panels or explain itself.
 *
 * An unknown slug is available: a view with no catalogue entry has no condition attached to it,
 * and inventing one here would hide a page for a reason no file states.
 */
export function capabilityOf(capabilities: Capabilities, slug: string): Capability {
  return capabilities[slug] ?? { slug, available: true, decided: true };
}

/**
 * Everything the shell needs, for the common case where a page wants both.
 *
 * The two awaits are joined rather than sequenced. `loadOuOptions` already issues a warehouse query
 * for an `all_ou` session, so this adds latency only when the capability cache is cold, and even
 * then it adds the probe's duration and not its sum with the Operating Unit lookup.
 */
export async function loadShell(
  session: Session,
  ouOptions: Promise<number[]>,
): Promise<{ ouOptions: number[]; capabilities: Capabilities; views: ViewDef[] }> {
  const [ou, capabilities] = await Promise.all([ouOptions, loadCapabilities(session)]);
  return { ouOptions: ou, capabilities, views: visibleViews(capabilities) };
}
