# Review Konsolidasi Modul Odoo — 2026-09-25

Hasil review 218 modul custom lintas tier (`core`, `compliance`, `control_plane`,
`operations`, `verticals`, `_tenants`, `ee_gap`, root) untuk tiga pertanyaan:
mana yang belum terkategori, mana yang layak digabung, dan mana yang masih
membawa identitas klien lama. Basis bukti: `docs/module-catalog.csv`
(diregenerasi hari ini), manifest di disk, dan **status terpasang nyata di 9
database live** — bukan tebakan dari nama modul.

Prinsip yang dipakai:

1. **Status terpasang menentukan risiko.** Memindah folder tier tidak mengubah
   nama teknis modul (addons_path memuat semua tier) — aman untuk DB mana pun.
   Menggabung/me-rename modul mengubah identitas di `ir_module_module` — butuh
   migrasi per DB.
2. **Satelit kecil belum tentu layak digabung.** Sebagian besar satelit adalah
   *glue module* yang sengaja dipisah agar modul induk tidak menyeret dependensi
   berat (mis. `custom_rental_quality_hook` memisahkan dep `quality_full` +
   `maintenance` dari `custom_rental`). Menggabungnya memaksa SEMUA pemasang
   induk ikut memasang dependensi itu.
3. **Bukti keep-split terbaik adalah pola instalasi**: keluarga `coretax`
   dipasang sebagai subset berbeda di tiap DB (lgx: bupot; admin: pajakku;
   acme_l10n: export) — pemisahannya terbukti berguna.

---

## 1. Modul root tanpa tier (5 modul) — kategorisasi

| Modul | Terpasang di | Status / Rekomendasi |
|---|---|---|
| `custom_pdp_core` | 7 DB | **SELESAI** — dilebur ke modul baru `compliance/custom_pdp` (lihat §2) |
| `custom_pdp_masking` | 7 DB | **SELESAI** — pindah ke `compliance/`, depends → `custom_pdp` |
| `custom_operating_unit` | 7 DB | → `core/` (dipakai lintas vertical: lgx, ndi, ppob, demo) |
| `custom_ppob` | 6 DB | → `verticals/` (lihat catatan duplikasi §3.1) |
| `custom_demo_seed` | 1 DB (bct_fixture) | → `operations/` (perkakas demo internal) |

Tiga pemindahan yang belum dieksekusi bernilai risiko **nol** terhadap database
(pindah folder saja), tapi menyentuh referensi path di repo (pre-commit ignores,
`30-metadata.sql` comment, dsb.) — pola yang sama dengan pemindahan PDP hari ini.

## 2. Duplikasi PDP — DIEKSEKUSI hari ini

`custom_pdp_core` (registry per-kolom `pdp.field.classification`, kontrak 01
beku, dibaca warehouse via SQL) dan `custom_pdp_taxonomy` (kamus semantik
`pdp.classification` + tag `x_pdp_classification_id`, 19 dependen) adalah dua
registry klasifikasi UU 27/2022 paralel yang terpasang berdampingan di 7 DB.

Diselesaikan dengan **redevelop menjadi satu modul `compliance/custom_pdp`**:

- Registry tetap kanonik (skema tabel & 5 kelas beku tidak berubah — warehouse
  dan `policy_master` tidak tersentuh); kamus roll-up ke kelas beku via field
  baru `pdp_class`; tag `ir.model.fields` menjadi proyeksi tersinkron
  (`_pdp_post_sync`, idempoten, jalan tiap `-u`); wizard tag write-through ke
  registry.
- Migrasi DB tanpa uninstall (gaya OpenUpgrade `merge_modules`):
  `scripts/migrate-pdp-module-merge.py`. 9/9 DB sudah dimigrasi; upgrade Odoo
  selesai di 7 DB, **menunggu persetujuan operator: `expomedia` (produksi) dan
  `acme`**.
- Hasil terverifikasi: registry seragam 1.159 baris di semua DB (athera_lgx &
  athera_admin yang tadinya tanpa registry kini lengkap), proyeksi terisi
  (650–843 tag/DB), 0 konflik roll-up, 0 xmlid yatim, 106 test Odoo lulus,
  `warehouse_ctl verify` + `sync-policy` hijau (894 kolom terklasifikasi, 0
  bocor `secret`).
- Bug laten ikut terjawab: kode klasifikasi `sensitive_pii`/`health`/
  `confidential` tidak pernah ada di seed — pemakainya (hook payroll, mixin
  audit, appraisal, referral, sertel upload) diselaraskan ke kosakata nyata.

## 3. Duplikasi lain yang DITEMUKAN (belum dieksekusi)

### 3.1 PPOB: root vs pack

- Root `custom_ppob` (`ppob.biller`, `ppob.transaction`) TERPASANG di 6 DB dan
  menjadi sumber CDC/dbt (assert pada `state`, `sla_seconds`,
  `operating_unit_id`) — tabelnya tidak boleh diganggu.
- Pack `verticals/custom_ppob_*` (12 modul) TIDAK terpasang di DB mana pun,
  dengan domain tumpang tindih (provider≈biller, sla, sale).
- Rekomendasi: root `custom_ppob` pindah folder ke `verticals/` (aman), lalu
  konsolidasi jangka panjang mengikuti pola PDP — pack menjadi satu-satunya
  implementasi, `ppob.transaction` tetap kanonik untuk warehouse. Kerjakan
  SEBELUM pack dipasang tenant pertama; sesudah itu biayanya naik kelas.

### 3.2 Withholding pajak: `custom_tax_id` vs `custom_pph_witholding`

Dua mesin withholding paralel, **terpasang berdampingan di expomedia +
athera_lgx**: `ee_gap/custom_tax_id` (`tax.withholding.rule/category`,
PPh 23/4(2)/26 + PPN DPP PMK 131) vs `compliance/custom_pph_witholding`
(`custom.witholding.engine/rate` — perhatikan typo "witholding"). Kandidat
konsolidasi berikutnya dengan pola PDP (registry kanonik + lapisan turunan),
tapi menyentuh perhitungan pajak produksi — butuh fase sendiri dengan uji
regresi angka. **Jangan merge kasual.**

## 4. Verdict penggabungan per keluarga

### 4.1 Kandidat MERGE yang layak (tidak terpasang di DB mana pun → tanpa migrasi)

| Merge | Ke | Alasan |
|---|---|---|
| `custom_rental_invoicing` (363 LOC) | `custom_rental` | dep tambahan hanya `account` |
| `custom_project_cr` + `custom_project_notify` | `custom_project_portfolio` | tak ada dep eksternal baru |
| `custom_finance_portal_sso` (128 LOC) + `custom_finance_budget` (251) | `custom_finance_portal` | mungil; dep `auth_oauth` ringan; budget memang bagian portal |
| `custom_ppob_wallet` (785) | `custom_ppob_core` | dep hanya ppob_core |
| `custom_ppob_commission` (632) | `custom_ppob_sale` | dep pph+bupot = compliance universal ID |
| **G1 ledger EE-gap**: `custom_account_batch_payment` + `custom_account_deferred` + `custom_account_reconcile` + `custom_payment_admin_fee` | modul baru `custom_account_ee_features` | keempatnya depends **hanya `account`**, maturity B — kandidat merge terbersih di repo |

Catatan eksekusi: modul ee_gap = repo terpisah; merge = hapus folder satelit +
salin kode ke induk + naikkan versi induk; karena tak terpasang di mana pun,
tidak ada migrasi DB.

### 4.2 KEEP SPLIT (pemisahan yang benar)

| Keluarga | Alasan |
|---|---|
| `custom_rental_bom_explosion`, `custom_rental_quality_hook` | glue ke `mrp` / `quality_full`+`maintenance` |
| `custom_project_api` | permukaan API, dep `auth_jwt` |
| `custom_finance_portal_sap` | adapter sistem eksternal (pola adapter_framework) |
| `custom_retail_import_pos/recon/api` | glue `point_of_sale` / `accounting_reports` / API `queue_job` |
| `custom_ppob_biller_digiflazz`, `_oracle_bridge`, `_pos_bridge`, `_pps_gateway`, `_va` | adapter/bridge per integrasi — pola adapter yang benar |
| **SPK (10 modul, core)** | **terpasang penuh di expomedia PRODUKSI** — jangan disentuh |
| Coretax (4 modul) | tiap DB memasang subset berbeda — split terbukti |
| Accounting inti: `custom_accounting_full` + `_recurring` + `_asset` + `_menu` | full terpasang produksi; asset/recurring opsional per tenant; menu = glue presentasi |
| Bank & payment: `custom_bank_import`, `custom_payment_id`, `custom_petty_cash` | tiga domain berbeda, berdiri sendiri |
| CoA: `l10n_id_coa_10d` vs `l10n_id_psak_custom` | dua template sah untuk profil tenant berbeda |
| WMS ee_gap (10 modul) | maturity A/B, generic; review pack-nya nanti bersama vertical logistik |
| Seeds `_tenants` (coa/opening_balance/asset_register) | data per-klien; memang tempatnya |
| `custom_ppob_rollup` | keep + **flag inversi tier** (verticals → ee_gap) |

### 4.3 Inversi tier yang tercatat (dep melawan urutan muat)

- `verticals/custom_ppob_rollup` → `ee_gap/custom_accounting_reports`
- `compliance/custom_pph_witholding` → `ee_gap/custom_hr_payroll_id`
- `ee_gap/custom_tax_id` → `ee_gap/custom_accounting_full` (wajar) tapi juga dipakai `verticals/custom_sale_show_date` (P&L by Show)
- `core/custom_hht_bridge`, `core/custom_product_barcode` → ee_gap/control_plane (preseden lama)
- `ee_gap/custom_coretax_export` + `custom_coretax_pajakku` secara domain milik `compliance/` — pindah tier berarti pindah repo; keputusan tersendiri.

Inversi tidak merusak instalasi (Odoo menyelesaikan dependensi lintas path),
tapi menandakan batas tier yang bocor — pertimbangkan saat konsolidasi
withholding (§3.2).

## 5. Modul eks-klien & status scrub

Keputusan: **scrub identitas, pertahankan modulnya** sebagai adapter/fitur
generic yang bisa dijual ulang.

- **SELESAI hari ini**: sisa string klien di `ee_gap/custom_retail_import*`
  (alamat mailbox POS + test), contoh di `CHANGELOG.md`, ADR 0002, dan
  `docs/module-catalog.md` (kini memakai placeholder `<client-a/b/c>`).
- **Peta rename dipindah keluar repo**: tabel rename bermuatan nama klien di
  `scripts/import-platform-addons.py` kini dibaca dari
  `scripts/client-renames.local.json` (untracked, git-excluded; salinan induk
  di luar repo). `--apply` menolak jalan tanpa berkas itu; konsumen read-only
  (refresh katalog, migrate-client-renames) degradasi anggun.
- Modul yang tetap berkarakter eks-klien namun sudah generic secara nama:
  `custom_retail_import*` (ingest mailbox/SFTP retail), `custom_finance_portal*`
  (engagement layer atas SAP), `custom_wms_sap_slotting`, `custom_esb_connector`,
  `custom_ppob_oracle_bridge`, `custom_intercompany_procurement`,
  `custom_asset_ops_reports` (vokabulari "drone fleet" — generic-kan saat dipakai
  klien non-aerial berikutnya).

## 6. Urutan eksekusi yang disarankan (setelah review ini disetujui)

1. **Selesaikan PDP**: upgrade `expomedia` + `acme` (perintah sudah disiapkan,
   butuh persetujuan operator).
2. **Pindah tier 3 modul root** (operating_unit → core, ppob → verticals,
   demo_seed → operations) — nol risiko DB, satu commit.
3. **Merge tak-terpasang** (§4.1) — per keluarga, satu PR per merge, commit
   ee_gap terpisah.
4. **Konsolidasi PPOB root-vs-pack** (§3.1) — sebelum pack dipasang tenant.
5. **Konsolidasi withholding** (§3.2) — fase sendiri, dengan regresi angka pajak.
