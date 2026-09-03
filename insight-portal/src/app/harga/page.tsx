export const dynamic = "force-dynamic";

const PRICING_API =
  process.env.INSIGHT_PORTAL_PRICING_API_URL ?? "http://marketing-site:3000/api/pricing";
const CONTACT_URL = process.env.INSIGHT_PORTAL_CONTACT_URL ?? "https://athera-digital.com/kontak";
const LOGIN_PATH = "/login";
const IMPLEMENTATION_NOTE = "Biaya implementasi menyesuaikan kebutuhan — Hubungi kami";

interface PublishedPlan {
  code: string;
  products: string[];
  price_month: string | null;
  currency: string;
}

async function insightPrice(): Promise<{ label: string; period: string | null }> {
  try {
    const res = await fetch(PRICING_API, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    const body = (await res.json()) as { plans: PublishedPlan[] };
    const plan = body.plans.find((p) => p.code === "insight");
    if (!plan || plan.price_month === null) return { label: "Hubungi kami", period: null };
    const n = Number(plan.price_month);
    const label = new Intl.NumberFormat("id-ID", {
      style: "currency",
      currency: plan.currency,
      maximumFractionDigits: 0,
    }).format(n);
    return { label, period: n > 0 ? "/ bulan" : null };
  } catch {
    // Read API unreachable: never invent a number. Show contact.
    return { label: "Hubungi kami", period: null };
  }
}

/**
 * Public pricing view for ATHERA Insight, shown to visitors who are not logged
 * in (the middleware exempts /harga). The price is read live from the registry
 * read API — no number is written in this file. Already a client? Sign in.
 */
export default async function HargaPage() {
  const { label, period } = await insightPrice();
  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "3rem 1.25rem" }}>
      <h1>ATHERA Insight</h1>
      <p>Dasbor yang angkanya bisa dipertanggungjawabkan, di atas data Anda sendiri.</p>
      <section
        style={{ border: "1px solid #2a2a2a", borderRadius: 16, padding: "1.5rem", marginTop: "1.5rem" }}
      >
        <p style={{ fontSize: "2rem", fontWeight: 600, margin: 0 }}>
          {label}
          {period ? <span style={{ fontSize: "1rem", fontWeight: 400 }}> {period}</span> : null}
        </p>
        <ul>
          <li>Dashboard &amp; visualisasi dari data Anda</li>
          <li>Data ter-masking sesuai kelas PDP</li>
          <li>Uji coba gratis tersedia</li>
        </ul>
        <p><small>{IMPLEMENTATION_NOTE}</small></p>
        <p style={{ display: "flex", gap: "1rem", marginTop: "1rem" }}>
          <a href={CONTACT_URL}>Diskusikan kebutuhan</a>
          <a href={LOGIN_PATH}>Sudah klien? Masuk</a>
        </p>
      </section>
    </main>
  );
}
