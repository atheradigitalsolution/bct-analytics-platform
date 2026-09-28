# -*- coding: utf-8 -*-
"""Papan hari ini: kunjungan berjalan, hunian bed, dan antrian yang bergerak.

KENAPA BERKAS INI ADA
---------------------
``hms_demo_builder.py`` membangun rumah sakitnya dan ``hms_demo_content.py``
membangun riwayatnya. Yang tidak dibangun keduanya adalah **hari ini**: ketiga
layar yang pertama kali dilihat calon klien — dasbor, papan bed, dan layar
antrian — membaca keadaan *sekarang*, dan keadaan sekarang justru yang paling
kosong. Nol kunjungan hari ini, hunian 3,3 %, dan 41 orang menunggu berbanding
nol yang dilayani adalah tiga angka yang, digabung, memperagakan rumah sakit
yang tutup.

Tiga keputusan yang membentuk berkas ini:

**Jam kedatangan dipadatkan di pagi hari.** Rumah sakit tidak menerima pasien
dengan laju rata; poliklinik penuh antara pukul 07.30 dan 11.00 lalu menipis.
Kedatangan yang tersebar rata adalah tanda pertama bahwa datanya dibangkitkan.

**Setiap jam disimpan sebagai UTC yang masih hari ini di Jakarta juga.** Odoo
menyimpan datetime tanpa zona; dasbor menghitung "hari ini" dari tanggal UTC
sementara siapa pun yang memeriksa lewat SQL akan mengubahnya ke
``Asia/Jakarta`` lebih dulu. Jendela yang memenuhi keduanya adalah UTC 00:00
sampai 16:59. Seluruh jam di bawah berada di dalamnya, dan tidak satu pun
melewati ``now`` — kunjungan yang datang dari masa depan lebih mencolok
daripada kunjungan yang tidak ada.

**Kombinasi klinisnya dibatasi pada yang sederhana dan benar.** Pembacanya
orang rumah sakit. Diagnosis yang tidak cocok dengan keluhan merusak
kredibilitas lebih parah daripada data yang sedikit, jadi setiap kasus di
bawah adalah satu diagnosis utama dengan keluhan, pemeriksaan, dan rencana
yang memang menyertainya.

IDEMPOTENSI
-----------
Semua yang dibuat di sini berjangkar ``ir.model.data`` seperti episode, jadi
``-u`` kedua tidak menambah apa pun.
"""
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# --- kunjungan hari ini ---------------------------------------------------
# (kunci, menit UTC sejak tengah malam, unit, spesialisasi, jenis, triase,
#  kemajuan, keluhan, (S, O, A, P), kode ICD-10, tarif tagihan, resume)
#
# Kemajuan: "finished" (pelayanan selesai, tagihan terbuka), "in_progress"
# (sedang di ruang periksa), "registered" (sudah ambil nomor, belum dipanggil).
TODAY_VISITS = [
    ("tv_um_01", 35, "POLI-UMUM", "SPU", "outpatient", None, "finished",
     "Batuk, pilek, dan nyeri tenggorokan sejak 3 hari",
     ("Batuk berdahak putih, pilek, nyeri menelan, tanpa sesak.",
      "Suhu 37,6 °C, faring hiperemis, tonsil tidak membesar, paru vesikuler.",
      "Infeksi saluran napas atas akut.",
      "Simptomatik, banyak minum, kontrol bila demam menetap 3 hari."),
     "J06.9", ("ADM-RJ", "KONS-UM"), True,
     {"temperature": 37.6, "pulse": 88}),
    ("tv_pd_01", 50, "POLI-PD", "INT", "outpatient", None, "finished",
     "Kontrol hipertensi, obat hampir habis",
     ("Tidak ada keluhan, obat amlodipin rutin, sisa 3 hari.",
      "TD 142/88, nadi 76, tidak ada edema tungkai, bunyi jantung normal.",
      "Hipertensi esensial belum terkontrol optimal.",
      "Lanjutkan amlodipin, kurangi garam, kontrol 1 bulan."),
     "I10", ("ADM-RJ", "KONS-SP"), True,
     {"systolic": 142, "diastolic": 88, "pulse": 76}),
    ("tv_an_01", 65, "POLI-ANAK", "ANA", "outpatient", None, "finished",
     "Anak demam dua hari tanpa kejang",
     ("Demam 2 hari, masih mau minum, tidak muntah, tidak kejang.",
      "Suhu 38,4 °C, anak aktif, faring hiperemis, turgor baik.",
      "Demam pada infeksi saluran napas atas akut.",
      "Parasetamol sesuai berat badan, kompres hangat, kontrol 2 hari."),
     "J06.9", ("ADM-RJ", "KONS-SP"), True,
     {"temperature": 38.4, "pulse": 116, "respiratory_rate": 26}),
    ("tv_um_02", 75, "POLI-UMUM", "SPU", "outpatient", None, "finished",
     "Nyeri ulu hati setelah telat makan",
     ("Nyeri ulu hati sejak semalam, mual, tidak muntah darah.",
      "Nyeri tekan epigastrium, bising usus normal, tidak ada tanda perdarahan.",
      "Gastritis.",
      "PPI 2 minggu, makan teratur, hindari kopi dan pedas."),
     "K29.7", ("ADM-RJ", "KONS-UM"), True,
     {"pain_score": 4}),
    ("tv_pd_02", 90, "POLI-PD", "INT", "outpatient", None, "finished",
     "Kontrol diabetes melitus rutin",
     ("Kontrol DM tipe 2, obat metformin diminum teratur, tidak ada luka kaki.",
      "BB 72 kg, TD 130/82, akral hangat, tidak ada neuropati sensorik.",
      "Diabetes melitus tipe 2 terkontrol sedang.",
      "Lanjutkan metformin, cek gula darah, kontrol 1 bulan."),
     "E11.9", ("ADM-RJ", "KONS-SP"), False,
     {"systolic": 130, "diastolic": 82, "weight_kg": 72, "height_cm": 162}),
    ("tv_gi_01", 105, "POLI-GIGI", "GIG", "outpatient", None, "finished",
     "Gigi geraham atas kiri berlubang dan ngilu",
     ("Ngilu saat minum dingin pada geraham atas kiri, tidak nyeri spontan.",
      "Karies media gigi 26, perkusi negatif, gusi tidak bengkak.",
      "Pulpitis reversibel gigi 26.",
      "Penambalan sementara, kontrol 1 minggu untuk tambal tetap."),
     "K04.0", ("ADM-RJ", "KONS-SP"), True,
     {"pain_score": 3}),
    ("tv_um_03", 120, "POLI-UMUM", "SPU", "outpatient", None, "finished",
     "Diare cair tiga kali sejak semalam",
     ("Diare cair 3 kali sejak semalam, tanpa lendir dan darah, masih mau minum.",
      "TD 118/76, nadi 88, turgor baik, bising usus meningkat.",
      "Gastroenteritis akut tanpa dehidrasi.",
      "Oralit tiap mencret, zinc 10 hari, kembali bila tidak mau minum."),
     "A09.9", ("ADM-RJ", "KONS-UM"), True,
     {"systolic": 118, "diastolic": 76, "pulse": 88}),
    ("tv_ob_01", 135, "POLI-OBG", "OBG", "outpatient", None, "finished",
     "Periksa kehamilan pertama, usia kehamilan 20 minggu",
     ("Hamil anak pertama, gerak janin dirasakan, tidak ada perdarahan.",
      "TD 112/70, TFU setinggi pusat, DJJ 144 kali per menit.",
      "Kehamilan 20 minggu, tunggal, hidup, intrauterin.",
      "Tablet tambah darah, edukasi tanda bahaya, kontrol 4 minggu."),
     "Z34.0", ("ADM-RJ", "KONS-SP"), True,
     {"systolic": 112, "diastolic": 70, "pulse": 84}),
    ("tv_an_02", 155, "POLI-ANAK", "ANA", "outpatient", None, "finished",
     "Anak batuk berdahak satu minggu",
     ("Batuk berdahak 1 minggu, tidak sesak, nafsu makan menurun ringan.",
      "Suhu 37,2 °C, retraksi tidak ada, paru vesikuler tanpa ronki.",
      "Infeksi saluran napas atas akut.",
      "Mukolitik, edukasi asap rokok di rumah, kontrol bila sesak."),
     "J06.9", ("ADM-RJ", "KONS-SP"), False,
     {"temperature": 37.2, "respiratory_rate": 24}),
    ("tv_pd_03", 175, "POLI-PD", "INT", "outpatient", None, "finished",
     "Sesak saat aktivitas pada penderita PPOK",
     ("Sesak memberat saat berjalan jauh, batuk berdahak, riwayat merokok 30 tahun.",
      "TD 128/80, RR 24, wheezing ekspirasi kedua lapangan paru, SpO2 95%.",
      "PPOK dengan eksaserbasi akut ringan.",
      "Bronkodilator inhalasi, kortikosteroid oral singkat, edukasi berhenti merokok."),
     "J44.1", ("ADM-RJ", "KONS-SP"), True,
     {"systolic": 128, "diastolic": 80, "respiratory_rate": 24, "spo2": 95}),
    ("tv_um_04", 195, "POLI-UMUM", "SPU", "outpatient", None, "finished",
     "Pusing berputar sejak pagi",
     ("Pusing berputar saat bangun tidur, mual, tidak ada gangguan pendengaran.",
      "TD 148/92, nadi 80, nistagmus horizontal ringan, kekuatan motorik normal.",
      "Hipertensi esensial dengan keluhan vertigo perifer.",
      "Antivertigo, mulai antihipertensi, kontrol 1 minggu."),
     "I10", ("ADM-RJ", "KONS-UM"), False,
     {"systolic": 148, "diastolic": 92, "pulse": 80}),
    ("tv_be_01", 220, "POLI-BEDAH", "BED", "outpatient", None, "finished",
     "Benjolan lipat paha kanan yang hilang timbul",
     ("Benjolan lipat paha kanan sejak 6 bulan, muncul saat mengedan, tidak nyeri.",
      "Benjolan lipat paha kanan reponibel, tidak nyeri tekan, bising usus positif.",
      "Hernia inguinalis dekstra reponibel.",
      "Rencana herniotomi elektif, penjelasan tindakan dan persiapan pra-operasi."),
     "K40.90", ("ADM-RJ", "KONS-SP"), True,
     {"pain_score": 1}),
    ("tv_an_03", 245, "POLI-ANAK", "ANA", "outpatient", None, "in_progress",
     "Anak mencret dan muntah sejak tadi pagi",
     ("Mencret cair 4 kali dan muntah 2 kali sejak pagi, masih mau minum.",
      "Suhu 37,8 °C, mata tidak cekung, turgor kembali cepat.",
      "Gastroenteritis akut tanpa dehidrasi.",
      "Oralit, zinc, observasi asupan cairan di poli."),
     "A09.9", ("ADM-RJ", "KONS-SP"), False,
     {"temperature": 37.8, "pulse": 112}),
    ("tv_pd_04", 275, "POLI-PD", "INT", "outpatient", None, "in_progress",
     "Lemas dan pucat sejak dua minggu",
     ("Lemas, pucat, dan mudah lelah 2 minggu, tidak ada perdarahan.",
      "Konjungtiva anemis, TD 110/70, nadi 96, tidak ada organomegali.",
      "Anemia, perlu penelusuran penyebab.",
      "Cek darah lengkap, mulai suplementasi besi, kontrol setelah hasil."),
     "D64.9", ("ADM-RJ", "KONS-SP"), False,
     {"systolic": 110, "diastolic": 70, "pulse": 96}),
    ("tv_um_05", 315, "POLI-UMUM", "SPU", "outpatient", None, "in_progress",
     "Demam dan nyeri otot sejak dua hari",
     ("Demam naik turun 2 hari, nyeri otot, tidak ada mimisan dan gusi berdarah.",
      "Suhu 38,2 °C, TD 116/74, uji torniket negatif, tidak ada ruam.",
      "Demam belum diketahui penyebabnya.",
      "Cek darah lengkap, parasetamol, kontrol besok untuk evaluasi trombosit."),
     "R50.9", ("ADM-RJ", "KONS-UM"), False,
     {"temperature": 38.2, "systolic": 116, "diastolic": 74}),
    ("tv_gi_02", 365, "POLI-GIGI", "GIG", "outpatient", None, "registered",
     "Kontrol tambalan gigi depan",
     None, None, None, False, None),
    ("tv_um_06", 415, "POLI-UMUM", "SPU", "outpatient", None, "registered",
     "Surat keterangan sehat untuk melamar kerja",
     None, None, None, False, None),
    ("tv_pd_05", 465, "POLI-PD", "INT", "outpatient", None, "registered",
     "Kontrol rutin tekanan darah dan ambil obat",
     None, None, None, False, None),
    # --- IGD ---------------------------------------------------------
    ("tv_igd_01", 70, "IGD", "SPU", "emergency", "yellow", "finished",
     "Nyeri perut melilit disertai muntah sejak dini hari",
     ("Nyeri perut melilit sejak dini hari, muntah 3 kali, belum makan.",
      "TD 112/72, nadi 96, nyeri tekan epigastrium, tidak ada defans muskular.",
      "Gastritis akut dengan muntah.",
      "Antiemetik dan PPI intravena, observasi 4 jam, rawat jalan bila membaik."),
     "K29.7", ("ADM-RJ", "KONS-UM", "TND-INF"), True,
     {"systolic": 112, "diastolic": 72, "pulse": 96, "pain_score": 6}),
    ("tv_igd_02", 185, "IGD", "SPU", "emergency", "green", "finished",
     "Luka lecet lengan kanan setelah terpeleset",
     ("Terpeleset di kamar mandi, lecet lengan kanan, tidak pingsan.",
      "Vulnus ekskoriatum lengan kanan 3 cm, tidak ada deformitas, GCS 15.",
      "Luka lecet akibat jatuh.",
      "Pembersihan luka dan balut, profilaksis tetanus, kontrol 3 hari."),
     "W19", ("ADM-RJ", "KONS-UM"), True,
     {"pain_score": 3}),
    ("tv_igd_03", 340, "IGD", "BED", "emergency", "red", "in_progress",
     "Nyeri dada kiri menjalar disertai keringat dingin",
     ("Nyeri dada kiri menjalar ke lengan kiri sejak 1 jam, keringat dingin.",
      "TD 158/96, nadi 104, SpO2 96%, akral dingin, JVP tidak meningkat.",
      "Nyeri dada akut, curiga sindrom koroner akut.",
      "Oksigen, akses intravena, EKG serial, konsultasi penyakit dalam segera."),
     "I10", ("ADM-RJ", "KONS-SP", "TND-INF"), False,
     {"systolic": 158, "diastolic": 96, "pulse": 104, "spo2": 96, "pain_score": 7}),
    ("tv_igd_04", 510, "IGD", "SPU", "emergency", "yellow", "in_progress",
     "Demam tinggi dan menggigil sejak tadi malam",
     ("Demam tinggi dan menggigil sejak semalam, nyeri saat berkemih.",
      "Suhu 39,0 °C, TD 108/68, nyeri ketok CVA kanan positif.",
      "Infeksi saluran kemih dengan demam.",
      "Hidrasi intravena, antipiretik, cek urinalisis, pertimbangkan rawat inap."),
     "N39.0", ("ADM-RJ", "KONS-UM", "TND-INF"), False,
     {"temperature": 39.0, "systolic": 108, "diastolic": 68, "pulse": 108}),
    ("tv_igd_05", 620, "IGD", "SPU", "emergency", "green", "registered",
     "Bengkak dan gatal setelah makan udang", None, None, None, False, None),
    ("tv_igd_06", 730, "IGD", "SPU", "emergency", "yellow", "registered",
     "Nyeri kepala hebat mendadak", None, None, None, False, None),
]

# --- hunian bed -----------------------------------------------------------
# (kunci, kode bed, spesialisasi DPJP, hari rawat, rencana pulang hari ini,
#  pasien anak, ICD-10, keluhan, (S, O, A, P), vital)
INPATIENT_CENSUS = [
    ("adm_mel_01", "MELATI-01-A", "INT", 3, False, False, "J18.9",
     "Demam tinggi dan sesak sejak tiga hari",
     ("Demam tinggi 3 hari, batuk berdahak kehijauan, sesak saat berjalan.",
      "Suhu 38,6 °C, RR 26, ronki basah kasar paru kanan bawah, SpO2 95%.",
      "Pneumonia komunitas.",
      "Antibiotik intravena, oksigen nasal, mukolitik, evaluasi foto toraks."),
     {"temperature": 38.6, "respiratory_rate": 26, "spo2": 95, "pulse": 98}),
    ("adm_mel_02", "MELATI-01-B", "INT", 5, True, False, "I50.0",
     "Sesak memberat dan kaki bengkak",
     ("Sesak memberat 4 hari, tidur dengan dua bantal, kaki bengkak.",
      "JVP meningkat, ronki basah halus kedua basal, edema pretibial +2.",
      "Gagal jantung kongestif dekompensasi.",
      "Diuretik intravena, restriksi cairan, pantau balans cairan harian."),
     {"systolic": 136, "diastolic": 84, "pulse": 96, "respiratory_rate": 24}),
    ("adm_mel_03", "MELATI-02-A", "BED", 2, False, False, "K80.2",
     "Nyeri perut kanan atas hilang timbul setelah makan berlemak",
     ("Nyeri perut kanan atas hilang timbul setelah makan berlemak, mual.",
      "Nyeri tekan hipokondrium kanan, Murphy sign negatif, tidak ikterik.",
      "Batu kandung empedu tanpa tanda kolesistitis akut.",
      "Analgetik, diet rendah lemak, rencana kolesistektomi laparoskopik elektif."),
     {"pain_score": 5, "pulse": 88}),
    ("adm_mel_04", "MELATI-03-A", "INT", 4, False, False, "N39.0",
     "Demam menggigil dan nyeri pinggang kanan",
     ("Demam menggigil 3 hari, nyeri saat berkemih, nyeri pinggang kanan.",
      "Suhu 38,9 °C, TD 104/66, nyeri ketok CVA kanan positif.",
      "Infeksi saluran kemih atas.",
      "Antibiotik intravena, hidrasi, kultur urin, evaluasi 48 jam."),
     {"temperature": 38.9, "systolic": 104, "diastolic": 66, "pulse": 104}),
    ("adm_mel_05", "MELATI-03-B", "INT", 6, True, False, "E11.9",
     "Gula darah sangat tinggi dengan lemas berat",
     ("Lemas berat, sering haus dan berkemih, obat tidak diminum 2 minggu.",
      "TD 126/78, nadi 96, turgor menurun ringan, tidak ada napas Kussmaul.",
      "Diabetes melitus tipe 2 dengan hiperglikemia berat tanpa ketoasidosis.",
      "Hidrasi, insulin, edukasi kepatuhan obat, konsultasi gizi."),
     {"systolic": 126, "diastolic": 78, "pulse": 96}),
    ("adm_mel_06", "MELATI-04-A", "INT", 2, False, False, "D64.9",
     "Lemas berat dan pucat dengan hemoglobin rendah",
     ("Lemas berat dan pucat 3 minggu, sesak saat aktivitas ringan.",
      "Konjungtiva anemis berat, TD 100/64, nadi 108, tidak ada perdarahan aktif.",
      "Anemia berat yang memerlukan transfusi.",
      "Transfusi packed red cell bertahap, penelusuran sumber perdarahan."),
     {"systolic": 100, "diastolic": 64, "pulse": 108}),
    ("adm_mel_07", "MELATI-05-A", "BED", 3, False, False, "K35.80",
     "Nyeri perut kanan bawah hebat sejak semalam",
     ("Nyeri perut kanan bawah sejak semalam, mual, muntah dua kali.",
      "Nyeri tekan McBurney positif, rebound tenderness positif, suhu 38,1 °C.",
      "Apendisitis akut.",
      "Apendektomi cito, antibiotik profilaksis, puasa pra-operasi."),
     {"temperature": 38.1, "pulse": 102, "pain_score": 8}),
    ("adm_ang_01", "ANGGREK-01-B", "INT", 5, False, False, "J44.1",
     "Sesak berat dengan mengi pada penderita PPOK",
     ("Sesak berat sejak 2 hari, batuk berdahak kental, riwayat PPOK lama.",
      "RR 28, wheezing ekspirasi kedua lapangan paru, SpO2 91% udara ruang.",
      "PPOK dengan eksaserbasi akut.",
      "Oksigen terkontrol, nebulisasi berkala, kortikosteroid, antibiotik."),
     {"respiratory_rate": 28, "spo2": 91, "pulse": 100}),
    ("adm_ang_02", "ANGGREK-02-A", "INT", 1, False, False, "A09.9",
     "Muntah dan diare cair dengan lemas berat",
     ("Muntah 8 kali dan diare cair 10 kali sejak kemarin, tidak bisa minum.",
      "Mata cekung, turgor menurun, TD 98/60, nadi 112.",
      "Gastroenteritis akut dengan dehidrasi sedang.",
      "Rehidrasi intravena, antiemetik, koreksi elektrolit, pantau balans cairan."),
     {"systolic": 98, "diastolic": 60, "pulse": 112}),
    ("adm_ang_03", "ANGGREK-02-B", "BED", 1, False, False, "K40.90",
     "Benjolan lipat paha kiri yang tidak dapat dimasukkan kembali",
     ("Benjolan lipat paha kiri sejak 1 tahun, sejak kemarin tidak bisa masuk.",
      "Benjolan lipat paha kiri ireponibel, tidak nyeri hebat, bising usus normal.",
      "Hernia inguinalis sinistra ireponibel tanpa tanda strangulasi.",
      "Puasa, observasi tanda strangulasi, rencana herniotomi hari ini."),
     {"pain_score": 4, "pulse": 88}),
    ("adm_ang_04", "ANGGREK-04-A", "INT", 8, False, False, "I63.9",
     "Kelemahan separuh badan kanan mendadak",
     ("Kelemahan separuh badan kanan dan bicara pelo mendadak 8 hari lalu.",
      "GCS 15, hemiparese kanan kekuatan 3, parese nervus VII sentral kanan.",
      "Stroke infark dengan hemiparese kanan.",
      "Antiplatelet, kontrol tekanan darah, fisioterapi, pencegahan luka tekan."),
     {"systolic": 158, "diastolic": 92, "pulse": 84}),
    ("adm_ang_05", "ANGGREK-04-B", "INT", 4, False, False, "N18.5",
     "Sesak dan bengkak seluruh tubuh pada penyakit ginjal kronik",
     ("Sesak, bengkak wajah dan tungkai, kencing sangat sedikit sejak 5 hari.",
      "TD 168/98, edema anasarka, ronki basah basal, konjungtiva anemis.",
      "Penyakit ginjal kronik stadium 5 dengan kelebihan cairan.",
      "Restriksi cairan dan garam, diuretik, persiapan akses hemodialisis."),
     {"systolic": 168, "diastolic": 98, "pulse": 92, "respiratory_rate": 24}),
    ("adm_ang_06", "ANGGREK-05-A", "INT", 2, False, False, "J18.9",
     "Demam dan sesak pada lanjut usia",
     ("Demam 2 hari, batuk berdahak, sesak, nafsu makan menurun.",
      "Suhu 38,3 °C, RR 26, ronki basah kasar paru kiri bawah, SpO2 93%.",
      "Pneumonia komunitas pada lanjut usia.",
      "Antibiotik intravena, oksigen nasal, mobilisasi bertahap, cegah aspirasi."),
     {"temperature": 38.3, "respiratory_rate": 26, "spo2": 93, "pulse": 94}),
    ("adm_ang_07", "ANGGREK-06-A", "INT", 2, True, False, "E87.6",
     "Lemas dan kram otot setelah diare berkepanjangan",
     ("Lemas seluruh badan dan kram tungkai setelah diare 4 hari.",
      "TD 106/68, nadi 98, refleks fisiologis menurun, tidak ada aritmia.",
      "Hipokalemia pada gastroenteritis akut.",
      "Koreksi kalium intravena terkontrol, pantau EKG, ulang elektrolit."),
     {"systolic": 106, "diastolic": 68, "pulse": 98}),
    ("adm_ang_08", "ANGGREK-07-A", "INT", 3, False, False, "A91",
     "Demam tinggi hari keempat dengan bintik merah",
     ("Demam tinggi 4 hari, nyeri kepala, nyeri otot, bintik merah di lengan.",
      "Suhu 38,7 °C, uji torniket positif, hepar tidak membesar, TD 110/70.",
      "Demam berdarah dengue derajat I.",
      "Cairan intravena terhitung, pantau trombosit dan hematokrit tiap 12 jam."),
     {"temperature": 38.7, "systolic": 110, "diastolic": 70, "pulse": 96}),
    ("adm_dah_01", "DAHLIA-01-A", "ANA", 3, False, True, "A91",
     "Anak demam tinggi hari keempat dan nyeri perut",
     ("Demam tinggi 4 hari, nyeri perut, nafsu makan turun, mimisan satu kali.",
      "Suhu 38,8 °C, uji torniket positif, nyeri tekan epigastrium, akral hangat.",
      "Demam berdarah dengue derajat I pada anak.",
      "Cairan intravena rumatan, pantau trombosit dan hematokrit tiap 12 jam."),
     {"temperature": 38.8, "pulse": 118, "respiratory_rate": 26}),
    ("adm_dah_02", "DAHLIA-02-A", "ANA", 2, False, True, "J18.9",
     "Anak sesak dan demam dengan napas cepat",
     ("Demam 3 hari, batuk, sesak, anak rewel dan malas minum.",
      "Suhu 38,5 °C, RR 44, retraksi subkostal, ronki basah halus kedua paru.",
      "Pneumonia pada anak.",
      "Antibiotik intravena, oksigen nasal, cairan rumatan, pantau napas."),
     {"temperature": 38.5, "respiratory_rate": 44, "spo2": 94, "pulse": 132}),
    ("adm_dah_03", "DAHLIA-03-A", "ANA", 1, False, True, "A09.9",
     "Anak muntah dan mencret dengan tanda kekurangan cairan",
     ("Mencret cair 9 kali dan muntah 5 kali sejak kemarin, malas minum.",
      "Mata cekung, turgor kembali lambat, nadi 140, anak rewel.",
      "Gastroenteritis akut dengan dehidrasi sedang pada anak.",
      "Rehidrasi intravena sesuai berat badan, zinc, pantau asupan dan keluaran."),
     {"pulse": 140, "temperature": 37.6, "respiratory_rate": 32}),
    ("adm_dah_04", "DAHLIA-04-A", "ANA", 2, True, True, "R50.9",
     "Anak demam tanpa sumber infeksi yang jelas",
     ("Demam 3 hari tanpa batuk, pilek, atau mencret; anak masih aktif.",
      "Suhu 38,2 °C, faring tenang, paru bersih, tidak ada ruam.",
      "Demam tanpa sumber infeksi yang jelas.",
      "Cairan rumatan, antipiretik, pantau suhu dan tanda infeksi fokal."),
     {"temperature": 38.2, "pulse": 120, "respiratory_rate": 28}),
]

# Siapa yang pantas mengisi slot poli tertentu. Anak berumur 54 tahun di Poli
# Anak, atau laki-laki pada kunjungan antenatal, adalah baris yang langsung
# terbaca salah oleh siapa pun yang bekerja di rumah sakit — dan tidak ada
# satu pun angka di layar yang terlihat keliru karenanya.
VISIT_PATIENT_RULE = {
    "POLI-ANAK": {"pediatric": True},
    "POLI-OBG": {"gender": "female", "min_age": 18, "max_age": 40},
}

# Urutan kelas dari yang tertinggi. Peserta JKN boleh NAIK kelas dengan
# membayar selisihnya; turun kelas terjadi juga di dunia nyata, tetapi di
# papan demo ia terbaca sebagai bed yang salah, bukan sebagai kebijakan.
CLASS_RANK = ["VVIP", "VIP", "I", "II", "III"]

# Loket pemanggil per layanan. Tanpa loket, tiket tidak bisa dipanggil sama
# sekali, sehingga antriannya hanya bisa bertambah.
QUEUE_COUNTERS = {
    "REG": ["LOKET-1", "LOKET-2"],
    "POLI-UMUM": ["PERIKSA-UM"],
    "POLI-PD": ["PERIKSA-PD"],
    "POLI-ANAK": ["PERIKSA-ANAK"],
    "POLI-OBG": ["PERIKSA-OBG"],
    "POLI-BEDAH": ["PERIKSA-BEDAH"],
    "POLI-GIGI": ["PERIKSA-GIGI"],
    "LAB": ["LAB-1"],
    "RAD": ["RAD-1"],
    "FAR": ["APOTEK-1", "APOTEK-2"],
    "KAS": ["KASIR-1", "KASIR-2"],
}

# Layanan poliklinik saja. _run_clinic_queue() menelusuri tiket yang MENUNGGU
# dan menggerakkannya mengikuti kunjungannya; tanpa penyaring ini, penyemaian
# KEDUA akan menemukan tiket LAB/RAD/FAR/KAS yang sengaja dibiarkan menunggu
# — mereka juga menempel pada kunjungan hari ini yang sudah selesai — lalu
# menyelesaikan semuanya. Antrian penunjang akan kosong pada `-u` berikutnya
# tanpa satu pun galat, dan hitungannya berbeda dari yang pertama.
CLINIC_QUEUE = ["POLI-UMUM", "POLI-PD", "POLI-ANAK", "POLI-OBG",
                "POLI-BEDAH", "POLI-GIGI"]

# (layanan, jumlah selesai, jumlah menunggu) untuk antrian penunjang hari ini.
SUPPORT_QUEUE = [("LAB", 7, 3), ("RAD", 3, 2), ("FAR", 9, 3), ("KAS", 8, 2)]


class HmsDemoContent(models.AbstractModel):
    _inherit = "hms.demo.content"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def _today_board(self):
        self.env["hms.demo.builder"]._assert_demo_database()
        self._today_visits()
        self._inpatient_census()
        self._queue_day()
        return True

    # ------------------------------------------------------------------
    # Pembagian pasien
    # ------------------------------------------------------------------
    def _available_patients(self):
        """Pasien yang belum dipakai papan hari ini, urut id.

        Penyaringnya memakai KUNCI JANGKAR papan, bukan status kunjungan.
        Menyaring dengan status akan melepaskan kembali pasien yang kunjungan
        rawat jalannya hari ini sudah ditutup — lalu memasukkannya ke bangsal
        dengan tanggal masuk tiga hari lalu, yaitu dua baris yang saling
        membantah pada pasien yang sama.
        """
        board_keys = ([spec[0] for spec in TODAY_VISITS]
                      + [spec[0] for spec in INPATIENT_CENSUS])
        taken = self.env["ir.model.data"].sudo().search([
            ("module", "=", "__simrs_demo__"),
            ("model", "=", "hms.encounter"),
            ("name", "in", board_keys),
        ])
        placed = self.env["hms.encounter"].browse(taken.mapped("res_id")).exists()
        # Dan siapa pun yang kunjungannya MASIH terbuka di tempat lain —
        # daftar tunggu operasi memegang kunjungan Poli Bedah yang sengaja
        # dibiarkan terbuka, dan memberi pasien yang sama kunjungan Poli Bedah
        # kedua hari ini ditolak _check_single_open_outpatient(). Penyemaian
        # akan berhenti di tengah upgrade, dan hanya kalau susunan pasiennya
        # kebetulan jatuh begitu.
        open_elsewhere = self.env["hms.encounter"].search([
            ("state", "in", ("registered", "in_progress", "admitted")),
        ])
        busy = set(placed.mapped("patient_id").ids) | set(open_elsewhere.mapped("patient_id").ids)
        return self.env["hms.patient"].search([
            ("state", "=", "active"), ("id", "not in", list(busy)),
        ], order="id")

    def _age_of(self, patient):
        if not patient.birth_date:
            return 0
        today = fields.Date.context_today(self)
        return (today - patient.birth_date).days // 365

    def _entitled_class_code(self, patient):
        """Kelas hak pasien menurut penjaminnya, atau None bila bebas memilih."""
        payer = patient.default_payer_id
        if payer and payer.code == "BPJS" and patient.bpjs_no:
            return {"1": "I", "2": "II", "3": "III"}.get(patient.bpjs_class or "3", "III")
        return None

    def _take_patient(self, pool, class_code=None, pediatric=False,
                      gender=None, min_age=None, max_age=None):
        """Ambil satu pasien yang pantas untuk slot ini, lalu keluarkan dari pool.

        Pencocokan kelas bukan kerapian: admisi yang menyatakan hak kelas VIP
        untuk peserta PBI adalah angka selisih kelas yang salah di tagihan,
        dan itu persis kolom yang akan ditunjuk orang keuangan. Naik kelas
        DIIZINKAN karena memang terjadi — yang ditolak adalah menempatkan
        peserta berhak kelas I di bed kelas III.
        """
        def fits(patient):
            age = self._age_of(patient)
            if pediatric != (age <= 17):
                return False
            if gender and patient.gender != gender:
                return False
            if min_age is not None and age < min_age:
                return False
            if max_age is not None and age > max_age:
                return False
            if class_code is None:
                return True
            entitled = self._entitled_class_code(patient)
            if entitled is None:
                return True
            return CLASS_RANK.index(class_code) <= CLASS_RANK.index(entitled)

        # Dua lintasan. Yang pertama mencari pasien yang haknya PERSIS kelas
        # bed ini; hanya kalau tidak ada, naik kelas diterima. Tanpa urutan
        # itu, pasien umum — yang cocok di kelas mana pun — habis dipakai
        # bangsal kelas atas lebih dulu, dan bangsal kelas III kehabisan
        # pasien yang berhak menempatinya.
        def exact(patient):
            return (class_code is not None
                    and self._entitled_class_code(patient) == class_code)

        for prefer_exact in (True, False):
            for patient in pool:
                if prefer_exact and not exact(patient):
                    continue
                if fits(patient):
                    pool.remove(patient)
                    return patient
        raise UserError(_(
            "Data demo kehabisan pasien yang cocok untuk slot ini "
            "(kelas %(c)s, anak: %(p)s, jenis kelamin: %(g)s). Tambah jumlah "
            "pasien di _patients() sebelum menambah slot di papan hari ini."
        ) % {"c": class_code or "bebas", "p": pediatric, "g": gender or "bebas"})

    # ------------------------------------------------------------------
    # 1. Kunjungan hari ini
    # ------------------------------------------------------------------
    def _today_at(self, minute_of_day):
        """Jam UTC hari ini, tidak pernah melewati ``now``.

        Pembatasan ke masa lalu bukan kehati-hatian berlebih: kunjungan yang
        tercatat datang beberapa jam dari sekarang muncul di papan sebagai
        baris yang mustahil, dan itu hal pertama yang ditunjuk orang.
        """
        now = fields.Datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        moment = start + timedelta(minutes=minute_of_day)
        latest = now - timedelta(minutes=5)
        return min(moment, latest)

    def _today_visits(self):
        pool = list(self._available_patients())
        for spec in TODAY_VISITS:
            (key, minute, unit_code, specialty, enc_type, triage, progress,
             complaint, note, icd10, bill_tariffs, want_summary, vitals) = spec
            if self._anchor(key):
                continue
            patient = self._take_patient(pool, **VISIT_PATIENT_RULE.get(unit_code, {}))
            self._keep(key, self._build_today_visit(
                patient, minute, unit_code, specialty, enc_type, triage,
                progress, complaint, note, icd10, bill_tariffs, want_summary,
                vitals,
            ))
        return True

    def _build_today_visit(self, patient, minute, unit_code, specialty, enc_type,
                           triage, progress, complaint, note, icd10,
                           bill_tariffs, want_summary, vitals):
        arrival = self._today_at(minute)
        unit = self._unit(unit_code)
        doctor = self._doctor(specialty)
        payer = patient.default_payer_id or self._payer("UMUM")
        encounter = self._open_encounter(
            patient, unit, doctor, payer, arrival, enc_type, complaint,
            triage=triage,
            arrival_mode="ambulance" if triage == "red" else "walk_in",
            start=progress != "registered",
        )
        if progress == "registered":
            return encounter
        self._observation(encounter, arrival + timedelta(minutes=8), **(vitals or {}))
        subjective, objective, assessment, plan = note
        note_type = "medical_initial" if enc_type == "emergency" else "soap"
        self._note(encounter, doctor, arrival + timedelta(minutes=20),
                   note_type, subjective, objective, assessment, plan)
        self._diagnoses(encounter, doctor, arrival + timedelta(minutes=25),
                        [(icd10, "primary", "final")])
        if progress == "in_progress":
            return encounter
        closed = min(
            arrival + timedelta(minutes=95 if enc_type == "emergency" else 55),
            fields.Datetime.now() - timedelta(minutes=2),
        )
        self._close_and_bill(encounter, closed, extra_tariffs=bill_tariffs)
        self.env["hms.klpcm"].analyze_encounter(encounter)
        if want_summary:
            self._summary_for(
                encounter,
                lab_summary="Tidak ada pemeriksaan penunjang yang memerlukan tindak lanjut.",
            )
            self.env["hms.klpcm"].analyze_encounter(encounter)
        return encounter

    # ------------------------------------------------------------------
    # 2. Hunian bed
    # ------------------------------------------------------------------
    def _inpatient_census(self):
        pool = list(self._available_patients())
        Bed = self.env["hms.bed"]
        for spec in INPATIENT_CENSUS:
            (key, bed_code, specialty, los, leaving_today, pediatric, icd10,
             complaint, note, vitals) = spec
            if self._anchor(key):
                continue
            bed = Bed.search([("code", "=", bed_code)], limit=1)
            if not bed:
                raise UserError(_("Bed %s tidak ada di data demo.") % bed_code)
            if bed.state != "vacant":
                # Bed sudah terisi oleh admisi lain: lewati tanpa memaksa,
                # karena memindahkan pasien yang sudah ada demi kerapian papan
                # adalah perubahan data klinis, bukan penyemaian.
                _logger.info("SIMRS demo: bed %s tidak kosong, slot dilewati", bed_code)
                continue
            class_code = bed.class_id.code if bed.class_id else None
            patient = self._take_patient(pool, class_code=class_code,
                                         pediatric=pediatric)
            self._keep(key, self._build_admission(
                patient, bed, specialty, los, leaving_today, icd10, complaint,
                note, vitals,
            ))
        return True

    def _build_admission(self, patient, bed, specialty, los, leaving_today,
                         icd10, complaint, note, vitals):
        arrival = fields.Datetime.now() - timedelta(days=los, hours=3)
        doctor = self._doctor(specialty)
        payer = patient.default_payer_id or self._payer("UMUM")
        encounter = self._open_encounter(
            patient, self._unit("RANAP"), doctor, payer, arrival, "inpatient",
            complaint, arrival_mode="referral",
        )
        self._observation(encounter, arrival + timedelta(minutes=15), **(vitals or {}))
        subjective, objective, assessment, plan = note
        self._note(encounter, doctor, arrival + timedelta(minutes=45),
                   "medical_initial", subjective, objective, assessment, plan)
        self._diagnoses(encounter, doctor, arrival + timedelta(minutes=50),
                        [(icd10, "primary", "final")])
        self._nursing_assessment(encounter, arrival + timedelta(minutes=30))
        entitled_code = self._entitled_class_code(patient)
        entitled = (self.env["hms.care.class"].search(
            [("code", "=", entitled_code)], limit=1) if entitled_code else bed.class_id)
        admission = self.env["hms.admission"].admit(
            encounter, bed, doctor,
            entitled_class=entitled or bed.class_id,
            # Kelas yang DITAGIHKAN adalah kelas bed yang benar-benar dipakai;
            # selisihnya terhadap hak kelas itulah angka naik kelas. Mengisinya
            # dengan hak kelas akan membuat kolom selisih selalu nol dan
            # fiturnya tidak pernah terlihat.
            charge_class=bed.class_id,
            source="emergency" if los <= 2 else "outpatient",
        )
        admitted_at = arrival + timedelta(hours=1)
        admission.write({"admitted_at": admitted_at})
        # Riwayat bed harus mulai pada jam yang sama dengan admisinya; kalau
        # tidak, lama pakai bed dan lama rawat menjawab dua angka berbeda
        # untuk pertanyaan yang sama.
        admission.assignment_ids.filtered("is_current").write({"from_at": admitted_at})
        if leaving_today:
            # Rencana pulang, bukan pulang: bed tetap terhitung terisi hari
            # ini, dan papan bed punya baris yang bergerak sore nanti.
            admission.action_plan_discharge()
        return encounter

    # ------------------------------------------------------------------
    # 3. Antrian hari ini
    # ------------------------------------------------------------------
    def _queue_day(self):
        today = fields.Date.context_today(self)
        Ticket = self.env["hms.qms.ticket"].sudo()
        self._close_out_previous_days(today)
        self._drop_stranded_tickets(today)
        counters = {c.code: c for c in self.env["hms.qms.counter"].search([])}
        missing = sorted({code for codes in QUEUE_COUNTERS.values()
                          for code in codes} - set(counters))
        if missing:
            raise UserError(_("Loket antrian belum ada: %s") % ", ".join(missing))
        self._run_clinic_queue(today, counters)
        self._run_registration_queue(counters)
        self._run_support_queue(counters)
        _logger.info("SIMRS demo: papan antrian hari ini — %s selesai, %s menunggu",
                     Ticket.search_count([("date", "=", today), ("state", "=", "finished")]),
                     Ticket.search_count([("date", "=", today), ("state", "=", "waiting")]))
        return True

    def _close_out_previous_days(self, today):
        """Nomor antrian hari kemarin tidak dibawa ke hari ini.

        Tiket yang masih menunggu dari tanggal yang sudah lewat menumpuk di
        layar sebagai orang yang menunggu berhari-hari. Di loket sungguhan
        nomor itu hangus saat jam pelayanan tutup.
        """
        stale = self.env["hms.qms.ticket"].sudo().search([
            ("date", "<", today),
            ("state", "in", ("waiting", "called", "serving", "held", "booked", "no_show")),
        ])
        if not stale:
            return 0
        counters = stale.mapped("counter_id")
        stale.action_cancel()
        # action_cancel tidak melepas tiket dari loketnya, sehingga layar
        # "sedang dipanggil" akan terus menampilkan nomor yang sudah hangus.
        counters.filtered(
            lambda c: c.current_ticket_id and c.current_ticket_id in stale
        ).write({"current_ticket_id": False})
        _logger.info("SIMRS demo: %s tiket antrian hari lampau dihanguskan", len(stale))
        return len(stale)

    def _drop_stranded_tickets(self, today):
        """Buang tiket hari ini yang lahir dari kunjungan hari lain.

        Setiap kunjungan demo yang dimundurkan tanggalnya tetap menerbitkan
        tiket pada hari PENYEMAIAN, bukan pada hari kunjungannya. Hasilnya
        lima belas orang menunggu di kasir untuk kunjungan yang ditutup dua
        minggu lalu — antrian yang tidak pernah bisa bergerak karena
        pasiennya sudah pulang. Yang berjangkar demo tidak disentuh.
        """
        anchored = set(self.env["ir.model.data"].sudo().search([
            ("module", "=", "__simrs_demo__"),
            ("model", "=", "hms.qms.ticket"),
        ]).mapped("res_id"))
        stranded = self.env["hms.qms.ticket"].sudo().search([
            ("date", "=", today),
        ]).filtered(
            lambda t: t.id not in anchored and (
                not t.encounter_id
                or not t.encounter_id.arrival_at
                or t.encounter_id.arrival_at.date() != today
            )
        )
        if not stranded:
            return 0
        counters = stranded.mapped("counter_id")
        counters.filtered(
            lambda c: c.current_ticket_id and c.current_ticket_id in stranded
        ).write({"current_ticket_id": False})
        count = len(stranded)
        stranded.unlink()
        orphan_journeys = self.env["hms.qms.journey"].sudo().search([
            ("ticket_ids", "=", False),
        ])
        if orphan_journeys:
            orphan_journeys.unlink()
        _logger.info("SIMRS demo: %s tiket terdampar dibuang", count)
        return count

    def _advance_ticket(self, ticket, counter, created, wait_minutes,
                        service_minutes, final):
        """Jalankan tiket lewat mesin statusnya, lalu betulkan stempel waktunya.

        Statusnya TIDAK ditulis langsung — panggil, layani, dan selesaikan
        tetap lewat aksinya, sehingga log tiket, papan loket, dan event
        display terbentuk persis seperti pada hari sungguhan. Yang ditulis
        sesudahnya hanya jam kejadiannya, karena aksi memakai ``now`` dan
        seluruh antrian akan tampak terjadi dalam satu detik yang sama —
        lama tunggu nol pada setiap baris KPI.
        """
        if ticket.state != "waiting":
            return ticket
        ticket.write({"created_at": created})
        ticket.action_call(counter)
        if final in ("serving", "finished"):
            ticket.action_serve()
        if final == "finished":
            ticket.action_finish()
        called = created + timedelta(minutes=wait_minutes)
        vals = {"called_at": called, "serving_at": called + timedelta(minutes=1)}
        if final == "finished":
            vals["finished_at"] = called + timedelta(minutes=1 + service_minutes)
        ticket.write(vals)
        return ticket

    def _run_clinic_queue(self, today, counters):
        """Tiket poliklinik mengikuti kemajuan kunjungannya sendiri."""
        tickets = self.env["hms.qms.ticket"].sudo().search([
            ("date", "=", today), ("state", "=", "waiting"),
            ("encounter_id", "!=", False),
            ("service_id.code", "in", CLINIC_QUEUE),
        ], order="id")
        for index, ticket in enumerate(tickets):
            encounter = ticket.encounter_id
            codes = QUEUE_COUNTERS.get(ticket.service_id.code)
            if not codes:
                continue
            counter = counters[codes[index % len(codes)]]
            created = encounter.arrival_at + timedelta(minutes=4)
            if encounter.state in ("finished", "discharged"):
                self._advance_ticket(ticket, counter, created, 22, 18, "finished")
            elif encounter.state == "in_progress":
                self._advance_ticket(ticket, counter, created, 19, 0, "serving")
        return True

    def _run_registration_queue(self, counters):
        """Loket pendaftaran: setiap kunjungan rawat jalan lewat sini dulu.

        Pasien IGD tidak mengambil nomor — mereka ditriase, dan mendaftarkan
        gawat darurat lewat antrian loket adalah alur yang tidak ada di rumah
        sakit mana pun.
        """
        service = self.env["hms.qms.service"].search([("code", "=", "REG")], limit=1)
        if not service:
            return False
        Ticket = self.env["hms.qms.ticket"].sudo()
        for index, spec in enumerate(TODAY_VISITS):
            key, minute, unit_code = spec[0], spec[1], spec[2]
            if unit_code == "IGD":
                continue
            reg_key = "qms_reg_%s" % key
            if self._anchor(reg_key):
                continue
            encounter = self._anchor(key)
            if not encounter:
                continue
            counter = counters[QUEUE_COUNTERS["REG"][index % 2]]
            created = encounter.arrival_at - timedelta(minutes=14)
            ticket = Ticket.issue(service, encounter=encounter,
                                  source="registration")
            self._advance_ticket(ticket, counter, created, 9, 4, "finished")
            self._keep(reg_key, ticket)
        # Orang yang baru masuk lobi: nomor sudah keluar, belum dipanggil.
        for offset in range(3):
            walk_key = "qms_reg_walkin_%s" % offset
            if self._anchor(walk_key):
                continue
            ticket = Ticket.issue(service, source="kiosk")
            ticket.write({
                "created_at": fields.Datetime.now() - timedelta(minutes=13 - offset * 4),
            })
            self._keep(walk_key, ticket)
        serving_key = "qms_reg_serving"
        if not self._anchor(serving_key):
            ticket = Ticket.issue(service, source="kiosk")
            self._advance_ticket(
                ticket, counters["LOKET-1"],
                fields.Datetime.now() - timedelta(minutes=17), 12, 0, "serving",
            )
            self._keep(serving_key, ticket)
        return True

    def _run_support_queue(self, counters):
        """Laboratorium, radiologi, apotek, dan kasir pada hari yang sama.

        Nomornya menempel pada kunjungan hari ini yang memang sudah dilayani
        atau sedang dilayani — tiket penunjang untuk pasien yang belum masuk
        ruang periksa adalah urutan yang terbalik.
        """
        Ticket = self.env["hms.qms.ticket"].sudo()
        served = [self._anchor(spec[0]) for spec in TODAY_VISITS
                  if spec[6] in ("finished", "in_progress")]
        served = [enc for enc in served if enc]
        if not served:
            return False
        for service_code, done, waiting in SUPPORT_QUEUE:
            service = self.env["hms.qms.service"].search(
                [("code", "=", service_code)], limit=1
            )
            if not service:
                continue
            codes = QUEUE_COUNTERS[service_code]
            for index in range(done):
                key = "qms_%s_done_%02d" % (service_code.lower(), index)
                if self._anchor(key):
                    continue
                encounter = served[index % len(served)]
                ticket = Ticket.issue(service, encounter=encounter, source="clinical")
                self._advance_ticket(
                    ticket, counters[codes[index % len(codes)]],
                    encounter.arrival_at + timedelta(minutes=40), 16, 11, "finished",
                )
                self._keep(key, ticket)
            for index in range(waiting):
                key = "qms_%s_wait_%02d" % (service_code.lower(), index)
                if self._anchor(key):
                    continue
                encounter = served[-(index + 1) % len(served)]
                ticket = Ticket.issue(service, encounter=encounter, source="clinical")
                ticket.write({
                    "created_at": fields.Datetime.now()
                    - timedelta(minutes=21 - index * 6),
                })
                self._keep(key, ticket)
        return True


class HmsDemoBuilder(models.AbstractModel):
    """Titik masuk penyemaian ulang papan hari ini tanpa ``-u`` penuh."""
    _inherit = "hms.demo.builder"

    @api.model
    def seed_today(self):
        self._assert_demo_database()
        return self.env["hms.demo.content"]._today_board()
