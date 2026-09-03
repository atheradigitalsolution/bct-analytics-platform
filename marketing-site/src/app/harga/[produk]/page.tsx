import { notFound } from "next/navigation";

import { getPublishedPlans, planByCode, formatPrice } from "@/lib/pricing";

export const dynamic = "force-dynamic";

const CONTACT_URL = process.env.MARKETING_SITE_CONTACT_URL ?? "https://athera-digital.com/kontak";
const IMPLEMENTATION_NOTE = "Biaya implementasi menyesuaikan kebutuhan — Hubungi kami";

// Per-product pricing, rendered from the registry. Meant to be served on each
// app's own domain (e.g. the odoo. edge routes /harga/odoo here before the Odoo
// Host rewrite). Prices are never written in this file.
const PRODUCTS: Record<string, { title: string; planCode: string | null; blurb: string; points: string[] }> = {
  insight: {
    title: "ATHERA Insight",
    planCode: "insight",
    blurb: "Dasbor yang angkanya bisa dipertanggungjawabkan, di atas data Anda sendiri.",
    points: ["Dashboard & visualisasi", "Data ter-masking sesuai kelas PDP", "Uji coba gratis tersedia"],
  },
  odoo: {
    title: "ATHERA Odoo",
    planCode: "odoo_care",
    blurb: "ERP yang mencerminkan proses Anda, dirawat dan didampingi tim kami.",
    points: ["Akses Odoo untuk tim Anda", "Custom module & pemeliharaan", "Training & pendampingan"],
  },
  agent: {
    title: "ATHERA Agent",
    planCode: null, // custom / contact — product 6 deferred
    blurb: "Asisten yang menjawab dari data Anda — LLM lokal, tanpa memindahkan data.",
    points: ["Pengetahuan dibatasi pemetaan field Insight", "Per-tenant, terisolasi", "Ketersediaan dijadwalkan"],
  },
};

export default async function ProductPricing({ params }: { params: Promise<{ produk: string }> }) {
  const { produk } = await params;
  const spec = PRODUCTS[produk];
  if (!spec) notFound();

  const plans = await getPublishedPlans();
  const plan = spec.planCode ? planByCode(plans, spec.planCode) : undefined;
  const priceLabel = plan ? formatPrice(plan.price_month, plan.currency) : "Custom";
  const period = plan && plan.price_month !== null && Number(plan.price_month) > 0 ? "/ bulan" : null;

  return (
    <>
      <section>
        <h1>{spec.title}</h1>
        <p className="lede">{spec.blurb}</p>
      </section>
      <section>
        <div className="card">
          <p className="price">
            {priceLabel}
            {period ? <span className="period"> {period}</span> : null}
          </p>
          <ul>
            {spec.points.map((p) => <li key={p}>{p}</li>)}
          </ul>
          <p className="impl"><small>{IMPLEMENTATION_NOTE}</small></p>
          <p className="cta"><a href={CONTACT_URL}>Diskusikan kebutuhan</a></p>
        </div>
      </section>
    </>
  );
}
