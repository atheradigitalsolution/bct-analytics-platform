import { NextResponse } from "next/server";

import { absolute } from "@/lib/redirect";
import { setPlanActive, setPlanPrice, PricingError } from "@/lib/pricing";
import { getSession } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * Edit a plan's price. Route access is already gated to `is_super_admin` by
 * middleware; we re-check the session here so the actor recorded in the audit
 * log is a real, verified super admin and never a fallback string.
 */
export async function POST(request: Request, { params }: { params: Promise<{ code: string }> }) {
  const session = await getSession();
  if (!session || session.is_super_admin !== true) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  const { code } = await params;
  const form = await request.formData();

  // Dua perbuatan, satu route, dipisahkan oleh sebuah field dan bukan oleh URL
  // yang bisa dipilih peramban. Menerbitkan/menarik paket tidak menyentuh harga,
  // dan menyunting harga tidak menyentuh keterbitan; menggabungkan keduanya dalam
  // satu formulir berarti satu klik mengubah dua hal yang tidak selalu ingin
  // diubah bersamaan.
  const intent = String(form.get("intent") ?? "price");
  if (intent === "active") {
    const isActive = String(form.get("is_active") ?? "") === "true";
    try {
      await setPlanActive(code, isActive, session.sub);
    } catch (e) {
      if (e instanceof PricingError) {
        return NextResponse.json({ error: e.message }, { status: 400 });
      }
      throw e;
    }
    return NextResponse.redirect(await absolute("/pricing"), { status: 303 });
  }

  // "custom" checkbox => null price ("Hubungi kami"). Otherwise parse a number.
  const custom = String(form.get("custom") ?? "") === "true";
  let priceMonth: number | null = null;
  if (!custom) {
    const raw = String(form.get("price_month") ?? "").trim();
    const n = Number(raw);
    if (raw === "" || !Number.isFinite(n) || n < 0) {
      return NextResponse.json({ error: "invalid_price" }, { status: 400 });
    }
    priceMonth = n;
  }
  const currency = String(form.get("currency") ?? "IDR").toUpperCase();

  try {
    await setPlanPrice(code, priceMonth, currency, session.sub);
  } catch (e) {
    if (e instanceof PricingError) {
      return NextResponse.json({ error: e.message }, { status: 400 });
    }
    throw e;
  }
  return NextResponse.redirect(await absolute("/pricing"), { status: 303 });
}
