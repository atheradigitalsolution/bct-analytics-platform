# Jebakan yang sudah dibayar — vertikal SIMRS (`custom_hms_*`)

Dokumen ini **bukan** dokumentasi fitur. Isinya hanya hal-hal yang sudah memakan
waktu berjam-jam, hampir semuanya karena **gagal tanpa terlihat gagal**.
Setiap perintah di sini sudah dijalankan apa adanya sebelum ditulis.

Ditulis 2026-09-20 selama membangun 24 modul di Odoo 19.0-20260817.

---

## 0. Cara memeriksa yang tidak berbohong

Bagian-bagian di bawah adalah jebakan **spesifik** Odoo 19 dan SIMRS. Bagian ini
adalah **metodenya**, dan ia berlaku di modul mana pun, juga saat bekerja
sendirian pada kode yang sudah Anda kenal betul.

Sepuluh cacat verifikasi dalam satu hari kerja melahirkan tujuh kebiasaan ini.
Kesepuluhnya berakibat sama — **laporan yang lebih meyakinkan daripada yang
dibenarkan pemeriksaannya** — dan gagal ke arah yang *menyenangkan*, sehingga
tidak ada yang memicu pemeriksaan ulang.

1. **Kontrol positif pada alat pemeriksanya sendiri.** Pemeriksaan yang belum
   pernah terlihat melaporkan sesuatu adalah pemeriksaan yang belum diuji.
   Rusak satu assert, sisipkan nama palsu, sentuh satu berkas — pastikan merah,
   lalu pulihkan dan verifikasi bersih.
2. **Bandingkan NAMA, bukan JUMLAH.** Dua `count()` yang sama bisa berarti satu
   hilang plus satu yatim. `comm -23` menjawab "yang mana".
3. **Periksa DUA ARAH.** Yang diharapkan tapi tidak ada, **dan** yang ada tapi
   tidak diharapkan. Yang kedua satu-satunya petunjuk bahwa sesuatu dulu dijaga
   dan sekarang tidak, tanpa ada yang memutuskan begitu.
4. **Pastikan yang Anda tanyai memang ada.** Nama model, field, key view, path
   endpoint — ambil dari `ir_model_fields`, `ir_ui_view`, `pg_constraint`,
   registrasi `@http.route`. Perintah yang benar atas nama yang karangan tetap
   menjawab, dan jawabannya menyesatkan. Ini yang paling sering terulang, bahkan
   setelah ditulis; membaca ulang perintah **tidak** dapat menangkapnya.
5. **Jangan salurkan keluaran gerbang ke `head`/`tail`.** Gandeng dengan `&&`
   atau periksa `${PIPESTATUS[0]}`. Kegagalan pemeriksaan dan hasil bersih harus
   **terlihat berbeda** — cetak "PEMERIKSAAN GAGAL — jangan baca sebagai aman",
   bukan angka nol yang menenangkan.
6. **Jangan tegakkan apa pun yang hasilnya bergantung mesin**, dan **jangan
   karang batas**. Pemeriksaan yang merah di satu mesin mengajari orang bahwa
   merah itu normal; batas yang ditebak menolak data sah tanpa petunjuk kenapa.
   Batas yang tidak diketahui pasti → parameter di `hms.settings`, bukan angka
   di kode.
7. **Pra-terbang sebelum menambah constraint** pada tabel berisi data. Kalau ada
   baris yang melanggar, `-u` gagal di tengah dan Anda menemukannya sebagai
   upgrade rusak, bukan sebagai temuan.

### Mana dari sepuluh butir ini yang benar-benar DIJAGA

Butir 10 berlaku ke dalam: dokumen ini menyatakan niat penulisnya, bukan
pengamatan atas apa yang dijaga hari ini. Diukur pada 2026-09-20:

**Nol dari sepuluh.** Tidak ada satu pun butir §0 yang ditegakkan tes di suite
ini. Rekonsiliasi constraint dua arah (butir 2 dan 3) dijalankan **manual** dari
shell, bukan sebagai tes — jadi ia tidak berjalan lagi besok kecuali seseorang
mengingatnya. Pemindai yang akan menegakkan sebagian butir masih dalam antrean.

Draf pertama tabel ini menulis "dua dari sepuluh". Itu **salah**, dan cara ia
salah adalah bentuk yang didaftar di butir 4: angka itu disalin dari pernyataan
sesi lain tentang **suite mereka**, lalu ditulis ke sini seolah mengukur suite
ini. Pemeriksaannya baru dijalankan setelah dokumennya terlanjur berbunyi "dua".

**Jangan membaca dokumen ini sebagai jaminan.** Dan perhatikan susunannya:
sembilan bagian di bawah §0 memuat jebakan yang sebagian akan punya pemindai;
§0 di atasnya tidak. Menaruh §0 lebih dulu membuatnya lebih terlihat — dan
karena itu **terlihat lebih dijaga daripada yang sebenarnya.** Kedekatan di satu
berkas bukan cakupan.

Konsekuensi praktisnya: butir yang tidak dijaga akan dilanggar, termasuk oleh
orang yang menulisnya. Ia dilanggar **sebelas kali dalam satu hari kerja** oleh
dua sesi yang sedang secara aktif saling memeriksa untuk bentuk-bentuk ini —
beberapa di antaranya di dalam pekerjaan yang isinya memeriksa bentuk itu, dan
satu di dalam paragraf yang melarangnya. Nilai daftar ini bukan pencegahan,
melainkan **mengenali gejalanya lebih cepat** — memangkas jam menjadi menit
setelah sesuatu menggigit.

**Parameter lahir dari TIGA tempat di SIMRS. Audit yang memeriksa satu tempat
bernama lebih luas daripada isinya:**

| Tempat | Jumlah | Mode kegagalan khasnya |
|---|---|---|
| field `hms.settings` | 41 | ditampilkan di form, tidak pernah dibaca kode |
| `ir.config_parameter` (`get_param`/`set_param`) | 9 | tidak ada di form, tidak ada yang tahu ia ada |
| variabel lingkungan (`os.environ`) | 22 | **dibaca kode tetapi tidak diberikan compose** |

Yang ketiga sudah menggigit: `SIMRS_DEMO_PASSWORD` dibaca `hms.demo.builder` tetapi
tidak pernah dideklarasikan di `compose/odoo.yml`, jadi nilai bawaan di kode sumber
dipakai **diam-diam** — sandi demo yang tertulis di pohon sumber terpasang di sistem
yang menghadap internet, tanpa satu pun galat.

Pemeriksaannya murah: kumpulkan `os.environ.get(...)` / `os.getenv(...)` dari seluruh
`.py` modul HMS (buang komentar dulu — penyebutan bukan pemakaian), kumpulkan kunci
`^\s+NAMA:` dari `compose/odoo.yml`, lalu selisihkan. Hasil yang benar adalah **daftar
kosong**, dan berikan kontrol positif dengan menyisipkan nama env karangan ke sisi
"dibaca" untuk memastikan selisihnya memang bisa berisi.

Per 2026-09-20: 22 dibaca, 22 diberikan, **0 hilang**.

8. **Laporkan VARIANS, bukan nilai, untuk keadaan yang berubah cepat.** "Jendela
   bebas", "0 berkas basi", "container sehat" adalah nilai sesaat yang mudah
   dilaporkan sebagai keadaan. Perintahnya benar, jawabannya benar, dan ia
   **kedaluwarsa sebelum dipakai**. Tidak ada ketelitian yang memperbaikinya.
   Kejadian nyata: tiga sampel berturut-turut atas jendela yang sama menjawab
   `bebas, bebas, SIBUK` — satu sampel akan benar dua kali dari tiga, tanpa cara
   membedakan mana yang sedang terjadi. Ambil beberapa sampel dan sebutkan
   sebarannya.

9. **`grep` di dalam container BUKAN bukti kode termuat.** Ia membaca berkas yang
   di-bind-mount; proses Odoo memuat kode saat impor. Keduanya terlihat identik
   dari luar, dan berbeda tepat setelah sebuah berkas diubah. Hal yang sama
   berlaku untuk probe perilaku di container `run --rm`: ia membuktikan
   **berkasnya** benar, bukan **prosesnya**. Satu-satunya yang menjawab adalah
   perbandingan mtime berkas terhadap `StartedAt` proses (lihat §2) — metode
   paling sederhana dari ketiganya. Kejadian nyata: **kedua sesi yang saling
   memeriksa seharian melaporkan `grep`-di-container satu sama lain sebagai
   bukti pemasangan, dan keduanya menerimanya tanpa bertanya.**

10. **Komentar adalah pernyataan NIAT penulisnya, bukan pengamatan atas
    perilakunya.** Keduanya bisa berpisah setelah refaktor yang tidak menyentuh
    komentarnya. Contoh nyata: sumber Odoo menyebut `password` ada di
    `_get_session_token_fields()` "untuk mekanisme invalidasi cache" — itu alasan
    seseorang menaruhnya di sana, bukan bukti cache benar-benar terbersihkan hari
    ini. Ukur perilakunya pada jalur yang sebenarnya, dalam **satu proses**, tanpa
    restart di antara langkahnya. Uji yang merestart di tengah akan hijau untuk
    mekanisme yang hanya bekerja setelah restart — yaitu tidak bekerja.

Dua bentuk yang **tidak** dapat ditangkap pemindai mana pun, dan hanya terlihat
dengan membandingkan nama terhadap spesifikasi yang melahirkannya:

- **Nama yang menyebut KATEGORI sementara isinya satu kasus.** Ia lolos review
  justru karena terbaca benar — tidak ada yang merah, dan pembacanya mencentangnya
  sebagai "sudah ditangani". Contoh nyata: `hms.delegation.is_currently_valid`
  hanya memeriksa rentang tanggal dan state, tidak pernah menanyakan apakah izin
  praktik dokter pemberi wewenang masih berlaku — padahal `hms.practitioner.license_state`
  ada justru karena izin kedaluwarsa. Kalau field itu bernama `is_within_date_range`,
  kekosongannya terlihat siapa pun. **Nama yang lebih abstrak selalu punya ruang
  untuk kosong di dalamnya tanpa terlihat.** Saring ke nama tingkat kategori
  (`*_status`, `*_valid`, `validate_*`, `*_compliance`), bukan ke semua nama.
- **Satu angka untuk dua batas.** Parameter yang benar untuk satu dimensi dan
  diam soal dimensi kedua yang sama mengikatnya. Contoh nyata:
  `hms.settings.max_call_count` (default 3) menandai pasien tidak hadir setelah
  tiga panggilan, **tanpa jeda minimum antar panggilan** — tiga ketukan dalam lima
  detik menandai pasien yang berdiri di depan loket sebagai tidak hadir. Aturannya
  punya dua dimensi (berapa kali, dalam rentang berapa lama); parameternya hanya
  mewakili satu.

Keduanya berbagi ciri: **tidak ada satu angka pun di sistem yang terlihat salah.**

**Pemindai adalah KODE YANG HARUS IKUT DIPELIHARA, dan mode kegagalan khasnya
bukan "tidak menangkap".** Ia adalah **menangkap hal yang salah sampai seseorang
melonggarkannya agar diam** — dan yang tersisa adalah centang hijau.

Kejadian nyata (sesi vertikal logistik, 2026-09-20): audit parameter dipasang,
lalu satu jam kemudian sebuah refaktor mengubah *cara* parameter dibaca. Delapan
belas parameter mendadak terbaca "tidak dipakai". Kodenya baik-baik saja;
**daftarnya** yang usang. Godaan wajarnya adalah menambahkan kedelapan belas itu
ke daftar pengecualian — yang akan mematikan pemeriksaannya diam-diam sambil
terasa seperti merapikan.

Konsekuensinya untuk setiap pemindai di `custom_hms_base`:

- Kunci **fakta**, bukan **cara**. Audit yang mencocokkan nama field di seluruh
  kode tahan refaktor; audit yang mencocokkan `get_param("nama")` rusak begitu
  pemanggilnya berubah. (Audit `hms.settings` di sini tahan refaktor **karena
  kebetulan** — field Odoo tidak punya satu bentuk panggilan kanonik. Itu bukan
  desain, dan bedanya baru terlihat saat sudah terlambat.)
- Pemindai yang mendadak merah setelah refaktor: **periksa daftarnya lebih dulu**,
  bukan kodenya. Melonggarkan pemindai adalah perubahan yang layak dipertanyakan
  sekeras perubahan kode.
- Pengecualian harus menyebut **alasan dan tanggal**, bukan hanya nama. Daftar
  pengecualian tanpa alasan adalah tempat pemeriksaan pergi untuk mati.

Dan satu aturan tentang aturan-aturan ini: **"sudah ada pemeriksaannya" bukan
jawaban.** Pemeriksaan menangkap *bentuk*, bukan *akibat*. Lihat tiga bentuk
"tes yang tidak berjalan" di §7 — akibatnya identik, dan tidak satu pun dari
tiga pemeriksaan menangkap dua lainnya.

Setiap perintah di dokumen ini sudah dijalankan apa adanya. Draf pertamanya
tidak, dan langsung memuat satu key view karangan.

---

## 1. `_sql_constraints` diabaikan SENYAP di Odoo 19

Odoo 19 hanya menulis `WARNING ... no longer supported` lalu jalan terus, dan
**constraint-nya tidak pernah dibuat di Postgres**. Modul terinstal "sukses"
sementara keunikan no. RM dan NIK tidak dijaga sama sekali.

Pakai atribut kelas: `_nama = models.Constraint("unique(kolom)", "Pesan")`.

**Jangan percaya log — rekonsiliasi PER NAMA, bukan per jumlah.** Dua `count()`
yang kebetulan sama bisa berarti satu constraint hilang plus satu yatim:

```bash
# daftar yang SEHARUSNYA ada, dari kode
python3 - <<'PY' | sort -u > /tmp/exp.txt
import glob, io, re
for f in sorted(glob.glob("addons/verticals/custom_hms_*/models/*.py")):
    s = io.open(f, encoding="utf-8", errors="replace").read()
    for blok in re.split(r"(?m)^class ", s)[1:]:
        m = (re.search(r'_name\s*=\s*["\']([\w.]+)["\']', blok)
             or re.search(r'_inherit\s*=\s*["\']([\w.]+)["\']', blok))
        if not m: continue
        tabel = m.group(1).replace(".", "_")
        for attr in re.findall(r"(?m)^\s{4}(_?\w+)\s*=\s*models\.Constraint\(", blok):
            print(f"{tabel}_{attr.lstrip('_')}")
PY
docker exec odoo19-bct-postgres psql -U odoo -d simrs_demo -tAc \
  "SELECT conname FROM pg_constraint WHERE conname LIKE 'hms\_%' AND contype IN ('c','u')" \
  | tr -d ' ' | sort -u > /tmp/act.txt
comm -23 /tmp/exp.txt /tmp/act.txt   # dideklarasikan tapi TIDAK ADA
comm -13 /tmp/exp.txt /tmp/act.txt   # ADA tapi yatim (model di-rename/dihapus)
```

Jalankan **kontrol positif** untuk rekonsiliasinya sendiri — sisipkan nama palsu
ke `/tmp/exp.txt` dan pastikan ia dilaporkan hilang; buang satu nama nyata dari
`/tmp/act.txt` dan pastikan itu juga tertangkap. Yang pertama menguji pembanding
hidup, yang kedua menguji daftar aktualnya benar.

**Penyaring `hms\_%` hanya sah selama tidak ada Constraint pada model warisan.**
Constraint pada model yang di-`_inherit` hidup di tabel milik modul lain
(`stock_lot_...`, `product_template_...`) dan tidak akan pernah muncul. Per
2026-09-20 tidak ada satu pun — diverifikasi dua arah. Kalau nanti ada, ubah
penyaringnya atau ia akan hilang tanpa suara.

## 2. `-u` TIDAK memuat ulang kode ke proses yang sedang jalan

Odoo melewati re-import bila `odoo.addons.<modul>` sudah ada di `sys.modules`.
Upgrade memperbarui skema dan data; worker HTTP tetap menjalankan kode lama.

| Yang berubah | Proses yang sedang jalan |
|---|---|
| Modul **baru** | dimuat — route langsung muncul |
| Modul lama + **berkas baru** | tidak dimuat — route 404 |
| Modul lama + **berkas diubah** | tidak dimuat — kode lama tetap dilayani |
| **Hibah grup** (tanpa berkas) | cache grup per-worker — hak "kadang ada kadang tidak" |

Yang terakhir tidak deterministik (tergantung worker) dan **tidak bisa**
ditangkap alat berbasis stempel waktu. `docker compose restart odoo` cukup;
`recreate` hanya perlu bila definisi container berubah (alias, environment, image).

**Deteksi kode basi — `find` di VPS ini `bfs`, bukan GNU findutils:**

```bash
raw=$(docker inspect -f '{{.State.StartedAt}}' odoo19-bct-odoo)
start=$(date -d "$raw" '+%Y-%m-%dT%H:%M:%S')   # WAJIB dikonversi
err=$(mktemp)
out=$(find addons/verticals -path '*custom_hms*' \( -name '*.py' -o -name '*.xml' \) \
      -newermt "$start" 2>"$err") || { echo "PEMERIKSAAN GAGAL — jangan baca sebagai aman"; cat "$err"; }
printf '%s' "$out" | grep -c .
```

Stempel mentah Docker (`...T00:45:39.16868887Z`, bernanodetik) **ditolak** `bfs`
dengan exit 1. Dibungkus `2>/dev/null | wc -l` ia menjadi `0` yang terbaca
"tidak ada yang perlu dimuat". Pisahkan stderr, periksa exit code.

## 3. Templat/view tidak ikut restart

Arch XML hidup di `ir_ui_view` dan hanya ditulis ulang saat `-u`. **Seluruh
cetakan SIMRS QWeb** — kartu pasien, gelang, resep, kuitansi. Restart tidak
memuat perubahan templat, dan PDF lama tetap terbentuk sempurna sehingga tidak
ada yang tampak rusak. Tanyakan ke basis datanya, jangan lihat hasilnya:

```bash
docker exec odoo19-bct-postgres psql -U odoo -d simrs_demo -tAc \
  "SELECT count(*) FROM ir_ui_view WHERE key='custom_hms_billing.report_receipt_document'"
```

Contoh key di atas diambil dari `ir_ui_view`, bukan dari ingatan. Draf pertama
dokumen ini memakai nama karangan (`custom_hms_base.report_patient_card`) yang
mengembalikan `0` — angka yang terbaca seperti jawaban. Ambil nama model, field,
key, dan path **dari sumbernya**: `ir_model_fields`, `ir_ui_view`, `pg_constraint`,
registrasi `@http.route`. Perintah yang benar atas nama yang salah tetap
menjawab, dan jawabannya menyesatkan.

## 4. Batas API: kembalikan `Response` = transaksi tetap di-commit

`hms_route` menangkap exception lalu **mengembalikan** `error_response(...)`.
Dispatcher Odoo membacanya sebagai sukses dan meng-commit apa pun yang sudah
ter-INSERT — klien diberi tahu "ditolak" sementara barisnya tersimpan. Sudah
diperbaiki dengan rollback di tiap cabang; **jangan cabut**.

Bentuk yang **lolos** dari perbaikan itu: handler yang menulis lalu
`return error_response(...)` **tanpa melempar**. Tidak ada exception, jadi blok
`except` tidak pernah jalan. Bungkus handler semacam itu dengan
`with self.env.cr.savepoint():`.

Menguji perbaikan rollback **wajib** dengan kontrol positif: permintaan yang
**sah** harus tetap tersimpan. Rollback yang kebablasan lulus uji penolakan
dengan gemilang.

## 5. Membuat record lalu `raise` = record TIDAK PERNAH tersimpan

Odoo membatalkan transaksi saat UserError naik. Pola "catat permintaan
otorisasi lalu tolak aksinya" **selalu gagal senyap** — supervisor tidak pernah
melihat antrian persetujuan. Pisahkan jadi dua panggilan: satu yang hanya
membuat (tanpa exception), satu yang menolak (tanpa create).

## 6. `noupdate` melekat pada RECORD, bukan pada modul penulis

Menambah `implied_ids` ke `res.groups` milik modul lain lewat `<record>` XML
**dilewati selamanya** bila record itu awalnya dibuat dalam `<data noupdate="1">`.
Sumbernya terbaca seolah hak sudah diberikan; basis datanya bilang tidak.
Pakai `post_init_hook` yang idempoten. Verifikasi ke `res_groups_implied_rel`.

## 7. Harness tes

- **`--workers=0` WAJIB.** Dengan `ODOO_WORKERS=2` Odoo memakai `PreforkServer`
  yang tidak punya atribut `httpd`; setiap `HttpCase` mati di `setUpClass` dengan
  `AttributeError` — terbaca sebagai "tes tidak jalan", bukan sebagai salah konfigurasi.
- **`--db-filter='.*'` khusus harness.** Produksi memakai `dbfilter = ^%d$` yang
  mengambil nama database dari label pertama `Host`; `HttpCase` memanggil
  `127.0.0.1` → label `"127"` → tidak ada database → **setiap rute 404**.
- **Pendeteksi kegagalan pernah BUTA.** Pola lama menuntut nama kelas berawalan
  `Test`, sedangkan seluruh modul HMS memakai `<Sesuatu>Case`; pencacah
  `failures=` tidak pernah bisa merah. Sekarang memakai baris resmi Odoo
  `N failed, M error(s) of K tests` **dan** memperingatkan bila baris itu tidak
  ditemukan sama sekali. `ERROR: setUpClass (...)` memakai kurung, bukan titik —
  pola yang menuntut titik akan melewatkan seluruh kelas yang lenyap.
- **Tes yang tidak berjalan, TIGA bentuk — dan tiap bentuk lolos dari pemeriksaan
  yang menangkap bentuk sebelumnya:**

  | Bentuk | Kenapa lolos |
  |---|---|
  | direktori `tests/` kosong | — |
  | berkas tes ada tapi **tidak diimpor** di `__init__.py` | direktorinya tidak kosong |
  | fungsi `test_*` **tersarang** di dalam fungsi lain | berkasnya ada DAN diimpor, sintaksisnya sah |

  Yang ketiga sudah menggigit: empat tes kasir berhenti dikoleksi karena sebuah
  fungsi tingkat-modul disisipkan di tengah badan kelas, yang mengakhiri kelasnya.
  Deteksinya lewat AST — `FunctionDef` bernama `test_*` berargumen pertama `self`
  yang tersarang di dalam `FunctionDef` lain; pesan galatnya harus menyebut **nama
  fungsi luarnya**, karena itu yang harus dipindahkan.

  Bentuk pertama **tidak dapat ditegakkan sebagai tes**: git tidak melacak
  direktori kosong, jadi tesnya merah di satu mesin dan hijau di mesin lain.
  Pemeriksaan yang hasilnya bergantung mesin lebih buruk daripada tidak ada — ia
  mengajari orang bahwa merah itu normal.

  **"Sudah ada pemeriksaannya" bukan jawaban.** Pemeriksaan menangkap *bentuk*,
  bukan *akibat*. Akibat ketiganya sama — tes yang tidak berjalan — dan tidak satu
  pun dari tiga pemeriksaan itu menangkap dua lainnya.

- **Kontrol negatif wajib pada perintah yang persis sama** dengan yang
  menghasilkan angka yang dikutip, bukan pada helper yang mirip. Rusak satu
  assert, pastikan merah, pulihkan, verifikasi berkas bersih.

## 8. API Odoo 19 lain yang berubah

- `stock.move.name` **dihapus** → `description_picking`. `stock.move.line` memakai
  `product_uom_id` + `quantity`; `stock.move` masih `product_uom` + `product_uom_qty`.
- `expiration_date` pada `stock.lot` datang dari modul CE **`product_expiry`**,
  bukan `stock`. Tanpa depend itu FEFO **diam-diam berubah jadi "lot mana saja"**.
  Produk wajib `tracking='lot'` DAN `use_expiration_date=True`.
- `res.users.groups_id` → `group_ids`.
- Search view: `<group string="..." expand="0">` untuk group-by **ditolak**;
  taruh `<filter context="{'group_by': ...}"/>` langsung di `<search>`.
- Satu `res.groups.privilege` **per sumbu peran**. Grup yang berbagi satu
  privilege dirender sebagai dropdown pilih-satu, jadi menyimpan form user
  membuang semua peran kecuali satu. SIMRS memakai 7 privilege terpisah.
- Model yang didefinisikan di `tests/` **tidak masuk registry**. Untuk menguji
  dispatch berbasis registry, `patch.object` pada kelas yang sudah ada.

## 9. Operasional

- **`docker logs --since` memakai waktu LOKAL.** `--since 07:25:17` menyaring dari
  `00:25:17Z` (UTC+7) dan menyeret galat berjam-jam sebelumnya. Pakai akhiran `Z`.
- **Jangan `--remove-orphans`** pada perintah compose apa pun — project
  `odoo19-bct` dipakai bersama vertikal lain; flag itu menyapu container mereka.
- Container Odoo, `.env`, dan `compose/odoo.yml` **dipakai bersama**. Koordinasikan
  sebelum apa pun yang menghancurkan container; `restart` dan `-u` biasa aman.
- **Periksa data sebelum menambah constraint** pada tabel berisi data — kalau ada
  baris yang melanggar, `-u` gagal di tengah dan Anda menemukannya sebagai
  upgrade rusak, bukan sebagai temuan.

## 10. Pencabutan token: JANGAN cache penandanya

`custom_hms_api/controllers/base.py` menyematkan klaim `stk` di setiap JWT —
hash atas kredensial pengguna — dan memeriksanya pada **setiap** permintaan.
Itulah yang membuat ganti sandi mencabut token yang sudah beredar; JWT
sendiri tidak dapat dicabut.

### Jebakan yang lolos dua belas kontrol

Versi pertama memakai `res.users._compute_session_token(sid)`, yang
di-dekorasi `@tools.ormcache('sid')`. **Seluruh uji hijau, dan fiturnya
tidak bekerja di tumpukan yang berjalan.**

Sebabnya: cache ormcache per proses. Proses lain hanya membuangnya kalau
penulisnya memanggil `registry.signal_changes()` — dan itu **hanya**
dipanggil di jalur dispatch RPC (`service/model.py:134,240`). Diukur di
mesin ini lewat pencacah `orm_signaling_default`:

```
ganti sandi lewat RPC / UI Odoo   -> 2 -> 3   worker lain DIKABARI
ganti sandi lewat `odoo shell`    -> 2 -> 2   worker lain TIDAK dikabari
```

Jadi pencabutan bekerja atau tidak **tergantung cara sandinya diganti**.
Itu jaminan yang berubah tanpa mengubah namanya, dan tidak dapat diterima
untuk fitur pencabutan.

Seluruh uji lolos karena `HttpCase` hidup di **satu proses**: yang mengubah
sandi dan yang membaca penanda adalah proses yang sama, jadi `clear_cache()`
mengenai cache yang sama. Termasuk uji "anti-hampa" SQL-mentah — ia juga
satu proses. **Dua belas kontrol, satu titik buta yang sama.**

### Bentuk sekarang

Penanda dihitung ulang setiap permintaan lewat dua primitif Odoo yang
**tidak** di-cache dan yang menyusun `_compute_session_token`:
`_session_token_get_values()` + `_session_token_hash_compute()`.
Diverifikasi menghasilkan hash yang identik.

Biaya terukur **0,309 ms** per permintaan (1,3 % dari p95 23,2 ms).
Endpoint p95 di tumpukan bayangan tanpa cache: 18,6 ms. Dibayar untuk
korektness. **Jangan** cache-kan lagi, dan **jangan** turunkan frekuensi
pemeriksaan menjadi "sesekali".

### Ketergantungan API privat — tiga nama

`_get_session_token_fields`, `_session_token_get_values`,
`_session_token_hash_compute`. Kalau Odoo mengubahnya, pencabutan berhenti
bekerja **tanpa melempar apa pun**. Dikunci oleh
`test_session_token_internals_still_exist` dan
`test_session_token_fields_still_cover_credentials`; keduanya gagal keras
dengan pesan yang menyebut alasannya. Jangan longgarkan.

### `sid` wajib membawa id pengguna

`@ormcache('sid')` menurunkan kunci **hanya** dari argumen yang disebut;
`self` tidak ikut. Dengan sid tetap, seluruh pengguna berbagi satu entri dan
satu ganti sandi melogout seluruh rumah sakit. Ditemukan oleh
`test_another_users_token_survives`. Meski kini tanpa cache, sid tetap
membawa id pengguna supaya hash antar pengguna tidak pernah bertabrakan.

### Batas kerangka uji — dan apa yang menggantikannya

`HttpCase` tidak dapat mementaskan dua proses, jadi pencabutan lintas proses
**tidak dapat diuji langsung oleh suite**. Penggantinya
`test_a_change_made_without_any_in_process_notice_is_seen`: SQL mentah
melewati `write()`, jadi tidak ada `clear_cache()` maupun
`signal_changes()` — pengamatan yang setara dengan worker lain mengubah
sandi. Versi ter-cache merah di situ.

**Suite hijau tidak membuktikan pencabutan lintas proses.** Bukti
sesungguhnya adalah uji hidup dua proses: terbitkan token lewat HTTP, ganti
sandi dari `odoo shell` terpisah, panggil ulang dengan token lama. Harus
401 seketika. Terakhir dijalankan 2026-09-20 di tumpukan bayangan: 401 pada
+0 s, +3 s, +10 s; token baru 200; token pengguna lain tetap 200.

