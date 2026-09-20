# LGX — Fasad API (`custom_lgx_api`)

> Versi 19.0.1.0.0 · lisensi LGPL-3 · `capability_tags`: logistics, api, rest, tracking, driver-app, scanner
> Depends: custom_lgx_job, custom_lgx_ff, custom_lgx_tms, custom_lgx_wms, rpc

## Purpose

Permukaan API bernama jelas di atas /json/2 untuk portal pelacakan, aplikasi pengemudi, dan pemindai gudang.

## Business Flow

**Jalur yang dipakai: modul `rpc` bawaan Odoo 19** — endpoint
``POST /json/2/<model>/<method>``, ``auth='bearer'``, API key sebagai Bearer
token. Nol dependensi eksternal, seluruhnya CE, dan ``api_doc`` menyajikan
``/doc`` dengan playground otomatis. Yang ditolak dan alasannya ada di §13.1
spesifikasi; ringkasnya: XML-RPC lama deprecated, OCA ``base_rest`` belum
dimigrasi ke 19.0, OCA ``auth_jwt`` tidak ada di 19.0.

**Model mentah TIDAK diekspos.** Setiap panggilan ``/json/2`` berjalan dalam
transaksi SQL sendiri, jadi operasi harus atomik dan tidak boleh dirangkai antar
request. Fasad ``lgx.api.service`` memberi satu method per operasi lengkap —
bukan empat panggilan yang harus berhasil semuanya.

**Bentuk respons mengikuti konvensi `custom_hms_api`** yang sudah terbukti
dipakai frontend Next.js di repo ini: amplop ``{"error": {"code", "message",
"fields"}}`` untuk galat, dan data polos untuk sukses. Membuat konvensi kedua di
repo yang sama berarti setiap frontend harus tahu sedang bicara dengan yang mana.

## Key Models

`lgx.api.service` · AbstractModel fasad; tidak punya tabel
`lgx.api.device` · perangkat lapangan dan kunci API per pengguna

## Public Methods

`track_shipment(reference)` · job / B/L / kontainer / referensi pelanggan
`list_jobs(filters, limit, offset)`
`driver_trip_list(driver_id)` · `driver_id` dari klien DIABAIKAN bila pemanggil pengemudi
`submit_pod(stop_id, signature, photos, received_by, …)` · satu operasi, aman diulang
`driver_update_trip(trip_id, action, odometer)` · aksi dibatasi daftar putih
`wms_task_list(kind, limit)` · picking terbuka untuk operator gudang
`scan_receive(picking_id, barcode, quantity, lot_name, owner_id)`
`scan_pick(picking_id, barcode, location, quantity)`
`wms_stock_by_client(client_id)`
`lgx.api.device.lgx_issue_key(user, kind, device_name)` · mengembalikan (device, kunci mentah)

Controller: `POST /lgx/api/device/register` (auth user) dan `/lgx/api/device/ping` (auth bearer).

## Integration Points

Dipakai `/opt/lgx/web` — pelacakan pelanggan, PWA pengemudi, PWA pemindai gudang.
`api_doc` menyajikan `/doc` dengan playground otomatis.

## Gotchas

**Setiap panggilan `/json/2` adalah transaksi SQL tersendiri.** Operasi yang butuh empat panggilan berurutan akan meninggalkan data separuh jadi begitu panggilan ketiga gagal karena sinyal putus — dan aplikasi pengemudi bekerja di tempat sinyal memang putus.

**`auth='bearer'` menerima API key ATAU sesi + header `Sec-Fetch-*`.** Jalur kedua hanya tersedia pada navigasi browser tingkat atas; server Node tidak bisa memakainya tanpa memalsukan proteksi CSRF. Karena itu perangkat lapangan memakai API key, dan kuncinya **per pengguna** — kunci bersama membuat setiap perangkat menjadi pengguna yang sama, dan record rule "pengemudi hanya melihat trip miliknya" berhenti berarti.

**Kunci perangkat WAJIB punya masa berlaku.** Odoo menolak kunci abadi untuk pengguna non-admin (`_check_expiration_date`), dan pengemudi jelas bukan admin — versi pertama kode ini memanggil `_generate(..., None)` dan akan gagal di perangkat pertama yang mendaftar. `sudo()` melewati BATAS DURASI grup, bukan keharusan punya masa berlaku; tanggalnya tetap diisi (90 hari, `lgx.device_key_days`).

**Pengemudi butuh akses baca `fleet.vehicle`.** Ditemukan tes, bukan ditebak: `driver_trip_list` menjawab 403 begitu ada trip sungguhan, karena ia membaca `vehicle_id.display_name`. Dengan nol trip ia tidak pernah menyentuh `fleet.vehicle` dan tampak sehat — kegagalan yang hanya muncul setelah ada data.

**Pemindaian pertama MENOLKAN kuantitas isian-otomatis Odoo** (`stock.picking.lgx_begin_scan`). Tanpa itu pemindaian menumpuk di atas tebakan sistem: picking dengan permintaan 600 yang dipindai 120 tercatat 720, lolos validasi, lalu meledak saat stok opname.

**`wms_stock_by_client`, `list_jobs` dan `wms_task_list` sengaja TIDAK memakai sudo.** Isolasi antar klien gudang adalah janji kontraktual; endpoint yang mem-bypass record rule akan membocorkan data lintas klien begitu ada satu pemanggil salah kunci.

**Barcode GS1-128 diurai di SISI SERVER.** Aturan penguraian berubah, dan perangkat lapangan adalah hal paling sulit diperbarui serentak.
