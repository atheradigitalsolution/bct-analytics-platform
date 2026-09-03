import { listPlans } from "@/lib/pricing";

export const dynamic = "force-dynamic";

function fmtIDR(price: string | null, currency: string): string {
  if (price === null) return "Custom — Hubungi kami";
  const n = Number(price);
  return new Intl.NumberFormat("id-ID", { style: "currency", currency, maximumFractionDigits: 0 }).format(n);
}

/**
 * Pricing editor — the single UI that sets prices for every product. Prices
 * are written to tenant_registry.plans and read by the public landing through
 * a view. Every change is audited (see lib/pricing.ts). This page is reachable
 * only by super admins (middleware); the product list itself is frozen.
 */
export default async function PricingPage() {
  const plans = await listPlans();
  return (
    <>
      <h1>Harga produk</h1>
      <p className="lede">
        Satu-satunya tempat harga diubah. Halaman <code>landing.athera-digital.com</code>{" "}
        membaca angka ini dari registry — tidak ada harga yang ditulis tangan di situs.
        Kosongkan / tandai <em>Custom</em> untuk menampilkan &quot;Hubungi kami&quot;.
        Setiap perubahan tercatat di <code>action_log</code>.
      </p>
      <p className="lede">
        <strong>Biaya implementasi</strong> sengaja tidak berangka di mana pun — ia
        selalu tampil sebagai &quot;menyesuaikan kebutuhan — Hubungi kami&quot; di landing.
      </p>
      <table>
        <thead>
          <tr><th>Plan</th><th>Produk</th><th>Harga / bln</th><th>Ubah</th></tr>
        </thead>
        <tbody>
          {plans.map((p) => (
            <tr key={p.code}>
              <td><code>{p.code}</code><br /><small>{p.display_name}</small></td>
              <td>{p.products.join(", ")}</td>
              <td>{fmtIDR(p.price_month, p.currency)}</td>
              <td>
                <form className="inline" method="POST" action={`/api/pricing/${p.code}`}>
                  <input
                    type="number"
                    name="price_month"
                    min="0"
                    step="1"
                    defaultValue={p.price_month ?? ""}
                    placeholder="kosong = custom"
                    aria-label={`Harga bulanan ${p.code}`}
                  />
                  <input type="hidden" name="currency" value={p.currency} />
                  <label>
                    <input type="checkbox" name="custom" value="true" defaultChecked={p.price_month === null} />{" "}
                    Custom
                  </label>
                  <button type="submit">Simpan</button>
                </form>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
