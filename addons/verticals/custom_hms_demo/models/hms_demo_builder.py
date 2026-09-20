# -*- coding: utf-8 -*-
"""Generates the fictional hospital.

Written as code rather than XML data files: two hundred medicines and fifty
patients in XML is several thousand unreadable lines, whereas a generator makes
the *shape* of the data visible — which is what someone reviewing the demo
actually needs to understand.

Everything is idempotent by code lookup, so re-running the builder tops the
data up instead of duplicating it.
"""
import logging
import os
import random
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# A fixed seed keeps the demo reproducible: the same patient names and the same
# bed occupancy every time, so a rehearsed presentation does not change under
# the presenter's feet.
SEED = 20260919

HOSPITAL = "RS Athera Medika"

CLINICS = [
    ("POLI-UMUM", "Poli Umum", "SPU"),
    ("POLI-PD", "Poli Penyakit Dalam", "INT"),
    ("POLI-ANAK", "Poli Anak", "ANA"),
    ("POLI-OBG", "Poli Kebidanan & Kandungan", "OBG"),
    ("POLI-BEDAH", "Poli Bedah", "BED"),
    ("POLI-GIGI", "Poli Gigi & Mulut", "GIG"),
]

SPECIALTIES = [
    ("SPU", "Dokter Umum", "001"),
    ("INT", "Penyakit Dalam", "002"),
    ("ANA", "Anak", "003"),
    ("OBG", "Obstetri & Ginekologi", "004"),
    ("BED", "Bedah Umum", "005"),
    ("GIG", "Gigi & Mulut", "006"),
    ("RAD", "Radiologi", "007"),
    ("PK", "Patologi Klinik", "008"),
    ("ANEST", "Anestesi", "009"),
]

DOCTORS = [
    ("Andi Wijaya", "SPU", "male"), ("Siti Rahmawati", "SPU", "female"),
    ("Bambang Sutrisno", "INT", "male"), ("Dewi Lestari", "INT", "female"),
    ("Eko Prasetyo", "ANA", "male"), ("Fitri Handayani", "ANA", "female"),
    ("Gunawan Saputra", "OBG", "male"), ("Hesti Nurhaliza", "OBG", "female"),
    ("Indra Kurniawan", "BED", "male"), ("Joko Santoso", "GIG", "male"),
    ("Kartika Sari", "RAD", "female"), ("Lukman Hakim", "PK", "male"),
]

NURSES = [
    ("Ani Rahayu", "primary"), ("Budi Hartono", "associate"), ("Citra Dewi", "charge_nurse"),
    ("Dian Permata", "head_nurse"), ("Endah Wulandari", "associate"),
    ("Fajar Nugroho", "er_nurse"), ("Gita Pratiwi", "icu_nurse"), ("Hadi Susanto", "associate"),
]

WARDS = [
    ("MELATI", "Melati", "general", [("I", 4), ("II", 6)]),
    ("ANGGREK", "Anggrek", "general", [("II", 6), ("III", 8)]),
    ("DAHLIA", "Dahlia", "pediatric", [("VIP", 2), ("I", 4)]),
]

# (code, name, category xmlid suffix, unit code or None, prices per class)
TARIFFS = [
    ("ADM-RJ", "Administrasi Rawat Jalan", "admin", None, {None: (25000, 25000, 0, 0)}),
    ("ADM-RI", "Administrasi Rawat Inap", "admin", None, {None: (75000, 75000, 0, 0)}),
    ("KONS-UM", "Konsultasi Dokter Umum", "consult", "POLI-UMUM",
     {None: (50000, 15000, 35000, 0)}),
    ("KONS-SP", "Konsultasi Dokter Spesialis", "consult", None,
     {None: (150000, 45000, 105000, 0)}),
    ("VISITE", "Visite Dokter Spesialis", "consult", None,
     {"VIP": (200000, 60000, 140000, 0), "I": (150000, 45000, 105000, 0),
      "II": (120000, 36000, 84000, 0), "III": (90000, 27000, 63000, 0)}),
    ("ASKEP", "Asuhan Keperawatan", "nursing", None,
     {"VIP": (150000, 150000, 0, 0), "I": (100000, 100000, 0, 0),
      "II": (75000, 75000, 0, 0), "III": (50000, 50000, 0, 0)}),
    ("KAMAR", "Akomodasi Kamar", "room", None,
     {"VVIP": (1200000, 1200000, 0, 0), "VIP": (800000, 800000, 0, 0),
      "I": (500000, 500000, 0, 0), "II": (300000, 300000, 0, 0),
      "III": (200000, 200000, 0, 0), "ICU": (1500000, 1500000, 0, 0)}),
    ("TND-HECT", "Hecting Luka (per 5 jahitan)", "procedure", "POLI-BEDAH",
     {None: (200000, 100000, 80000, 20000)}),
    ("TND-INF", "Pemasangan Infus", "procedure", None, {None: (75000, 40000, 25000, 10000)}),
    ("TND-NEB", "Nebulizer", "procedure", "POLI-ANAK", {None: (85000, 50000, 25000, 10000)}),
    ("LAB-DL", "Darah Lengkap", "lab", "LAB", {None: (85000, 85000, 0, 0)}),
    ("LAB-GDS", "Gula Darah Sewaktu", "lab", "LAB", {None: (35000, 35000, 0, 0)}),
    ("LAB-WIDAL", "Widal", "lab", "LAB", {None: (95000, 95000, 0, 0)}),
    ("RAD-THX", "Rontgen Thorax PA", "rad", "RAD", {None: (150000, 110000, 40000, 0)}),
    ("RAD-USG", "USG Abdomen", "rad", "RAD", {None: (250000, 150000, 100000, 0)}),
]

LAB_PARAMETERS = [
    # code, name, unit, ranges [(gender, age_from, age_to, low, high, crit_low, crit_high)]
    ("HB", "Hemoglobin", "g/dL", [
        ("male", 15, 0, 13.0, 17.0, 7.0, 20.0),
        ("female", 15, 0, 12.0, 15.0, 7.0, 20.0),
        (None, 0, 14, 11.0, 14.0, 6.0, 19.0),
    ]),
    ("WBC", "Leukosit", "10³/µL", [(None, 0, 0, 4.0, 11.0, 1.5, 30.0)]),
    ("PLT", "Trombosit", "10³/µL", [(None, 0, 0, 150.0, 450.0, 50.0, 1000.0)]),
    ("HCT", "Hematokrit", "%", [
        ("male", 15, 0, 40.0, 52.0, 20.0, 60.0),
        ("female", 15, 0, 36.0, 47.0, 20.0, 60.0),
    ]),
    ("GDS", "Gula Darah Sewaktu", "mg/dL", [(None, 0, 0, 70.0, 140.0, 45.0, 400.0)]),
]

MEDICINE_BASE = [
    ("Parasetamol", "500 mg", "TAB", ["oral"], False, False, 3000),
    ("Amoksisilin", "500 mg", "KAP", ["oral"], False, False, 4500),
    ("Amlodipin", "10 mg", "TAB", ["oral"], False, False, 2500),
    ("Metformin", "500 mg", "TAB", ["oral"], False, False, 1500),
    ("Omeprazol", "20 mg", "KAP", ["oral"], False, False, 5000),
    ("Ranitidin", "150 mg", "TAB", ["oral"], False, False, 2000),
    ("Ceftriakson", "1 g", "VIAL", ["iv"], False, False, 35000),
    ("Deksametason", "5 mg/mL", "AMP", ["iv", "im"], False, False, 6000),
    ("Furosemid", "40 mg", "TAB", ["oral"], False, False, 2200),
    ("Insulin Glargin", "100 IU/mL", "PEN", ["sc"], True, False, 180000),
    ("Heparin", "5000 IU/mL", "VIAL", ["iv"], True, False, 120000),
    ("Kalium Klorida", "7,46%", "AMP", ["iv"], True, False, 25000),
    ("Morfin", "10 mg/mL", "AMP", ["iv", "im"], True, True, 45000),
    ("Petidin", "50 mg/mL", "AMP", ["im"], True, True, 50000),
    ("Diazepam", "5 mg", "TAB", ["oral"], False, True, 3500),
    ("Salbutamol", "2,5 mg", "NEB", ["inhalasi"], False, False, 12000),
    ("Ambroksol", "30 mg", "TAB", ["oral"], False, False, 2500),
    ("Cetirizin", "10 mg", "TAB", ["oral"], False, False, 2800),
    ("Ibuprofen", "400 mg", "TAB", ["oral"], False, False, 3200),
    ("Ondansetron", "4 mg/2 mL", "AMP", ["iv"], False, False, 18000),
]

FIRST_NAMES_M = ["Agus", "Budi", "Cahyo", "Dedi", "Eko", "Fajar", "Gilang", "Hendra",
                 "Irfan", "Joko", "Kurnia", "Lukman", "Made", "Nanang", "Oka", "Putra",
                 "Rizky", "Slamet", "Teguh", "Wahyu"]
FIRST_NAMES_F = ["Ayu", "Bunga", "Citra", "Dewi", "Eka", "Fitri", "Gita", "Hesti",
                 "Indah", "Juwita", "Kartika", "Lestari", "Maya", "Novi", "Putri",
                 "Ratna", "Sari", "Tika", "Wulan", "Yuni"]
LAST_NAMES = ["Santoso", "Wijaya", "Pratama", "Kusuma", "Setiawan", "Hidayat", "Nugroho",
              "Saputra", "Rahmawati", "Permata", "Hartono", "Susanto", "Maulana",
              "Firmansyah", "Anggraini", "Puspita", "Handayani", "Lestari"]


class HmsDemoBuilder(models.AbstractModel):
    _name = "hms.demo.builder"
    _description = "Pembangun Data Demo SIMRS"

    # --- entry point ------------------------------------------------------
    @api.model
    def build_all(self):
        random.seed(SEED)
        self._settings()
        self._specialties()
        units = self._units()
        self._tariffs(units)
        self._lab_parameters()
        practitioners = self._practitioners(units)
        wards = self._wards()
        self._depots()
        self._medicines()
        self._payers()
        self._qms(units, practitioners)
        self._schedules(units, practitioners)
        self._nursing(wards)
        self._cashier()
        self._nursing_masters()
        self._patients()
        self._users(practitioners)
        _logger.info("SIMRS: data demo selesai dibuat")
        return True

    # --- helpers ----------------------------------------------------------
    def _get_or_create(self, model, domain, vals):
        record = self.env[model].search(domain, limit=1)
        if record:
            return record
        return self.env[model].create(vals)

    # --- master data ------------------------------------------------------
    def _settings(self):
        settings = self.env["hms.settings"].get_settings()
        settings.write({
            "hospital_name": HOSPITAL,
            "hospital_code": "3273015",
            "hospital_class": "c",
            "hospital_address": "Jl. Kesehatan Raya No. 1, Bandung, Jawa Barat 40123",
            "hospital_phone": "(022) 555-0100",
            "director_name": "dr. Hendra Gunawan, M.Kes",
        })
        return settings

    def _specialties(self):
        for code, name, bpjs in SPECIALTIES:
            self._get_or_create("hms.specialty", [("code", "=", code)], {
                "code": code, "name": name, "bpjs_code": bpjs,
            })

    def _units(self):
        units = {}
        for code, name, specialty_code in CLINICS:
            specialty = self.env["hms.specialty"].search([("code", "=", specialty_code)], limit=1)
            units[code] = self._get_or_create("hms.unit", [("code", "=", code)], {
                "code": code, "name": name, "type": "outpatient_clinic",
                "specialty_id": specialty.id, "bpjs_poli_code": specialty.bpjs_code,
                "building": "Gedung A", "floor": "1", "area_m2": 40,
            })
        support = [
            ("IGD", "Instalasi Gawat Darurat", "emergency", 120),
            ("RANAP", "Instalasi Rawat Inap", "inpatient", 600),
            ("LAB", "Laboratorium", "lab", 60),
            ("RAD", "Radiologi", "radiology", 80),
            ("FAR", "Instalasi Farmasi", "pharmacy", 50),
            ("MANAJ", "Manajemen & Administrasi", "admin", 100),
        ]
        for code, name, kind, area in support:
            units[code] = self._get_or_create("hms.unit", [("code", "=", code)], {
                "code": code, "name": name, "type": kind, "area_m2": area,
                "is_revenue_unit": kind not in ("admin",),
                "overhead_pool": kind == "admin",
            })
        return units

    def _tariffs(self, units):
        category_map = {
            "admin": "custom_hms_base.tariff_cat_admin",
            "consult": "custom_hms_base.tariff_cat_consult",
            "procedure": "custom_hms_base.tariff_cat_procedure",
            "nursing": "custom_hms_base.tariff_cat_nursing",
            "room": "custom_hms_base.tariff_cat_room",
            "lab": "custom_hms_base.tariff_cat_lab",
            "rad": "custom_hms_base.tariff_cat_rad",
        }
        classes = {c.code: c for c in self.env["hms.care.class"].search([])}
        for code, name, category_key, unit_code, prices in TARIFFS:
            category = self.env.ref(category_map[category_key])
            tariff = self._get_or_create("hms.tariff", [("code", "=", code)], {
                "code": code, "name": name, "category_id": category.id,
                "unit_id": units[unit_code].id if unit_code else False,
            })
            for class_code, (total, facility, medical, consumable) in prices.items():
                care_class = classes.get(class_code) if class_code else None
                exists = tariff.price_ids.filtered(
                    lambda p, c=care_class: p.class_id == (c or self.env["hms.care.class"])
                    and not p.payer_id
                )
                if exists:
                    continue
                self.env["hms.tariff.price"].create({
                    "tariff_id": tariff.id,
                    "class_id": care_class.id if care_class else False,
                    "price_total": total,
                    "amount_facility": facility,
                    "amount_medical": medical,
                    "amount_consumable": consumable,
                })

    def _lab_parameters(self):
        panel = self.env["hms.tariff"].search([("code", "=", "LAB-DL")], limit=1)
        for code, name, uom, ranges in LAB_PARAMETERS:
            parameter = self._get_or_create("hms.lab.parameter", [("code", "=", code)], {
                "code": code, "name": name, "uom_name": uom, "value_type": "numeric",
                "specimen_type": "Darah EDTA", "tat_minutes": 60,
            })
            if not parameter.range_ids:
                for gender, age_from, age_to, low, high, crit_low, crit_high in ranges:
                    self.env["hms.lab.reference.range"].create({
                        "parameter_id": parameter.id, "gender": gender,
                        "age_from": age_from, "age_to": age_to,
                        "ref_low": low, "ref_high": high,
                        "critical_low": crit_low, "critical_high": crit_high,
                    })
            if panel and code in ("HB", "WBC", "PLT", "HCT"):
                panel.write({"lab_parameter_ids": [(4, parameter.id)]})
        gds = self.env["hms.tariff"].search([("code", "=", "LAB-GDS")], limit=1)
        gds_param = self.env["hms.lab.parameter"].search([("code", "=", "GDS")], limit=1)
        if gds and gds_param:
            gds.write({"lab_parameter_ids": [(4, gds_param.id)]})

    def _practitioners(self, units):
        practitioners = {}
        nik_seq = 3273010101800001
        for index, (name, specialty_code, gender) in enumerate(DOCTORS):
            specialty = self.env["hms.specialty"].search([("code", "=", specialty_code)], limit=1)
            unit_codes = [c[0] for c in CLINICS if c[2] == specialty_code] or ["POLI-UMUM"]
            if specialty_code == "RAD":
                unit_codes = ["RAD"]
            if specialty_code == "PK":
                unit_codes = ["LAB"]
            practitioner = self._get_or_create(
                "hms.practitioner", [("nik", "=", str(nik_seq + index))], {
                    "name": name, "title_prefix": "drg." if specialty_code == "GIG" else "dr.",
                    "title_suffix": "" if specialty_code == "SPU" else f"Sp.{specialty_code}",
                    "type": "dentist" if specialty_code == "GIG" else "doctor",
                    "nik": str(nik_seq + index), "gender": gender,
                    "specialty_id": specialty.id,
                    "unit_ids": [(6, 0, [units[c].id for c in unit_codes])],
                    "primary_unit_id": units[unit_codes[0]].id,
                    "bpjs_doctor_code": f"D{index + 1:03d}",
                    "str_no": f"STR-{index + 1:05d}",
                    "str_valid_to": fields.Date.add(fields.Date.context_today(self), days=900),
                    "can_be_dpjp": True,
                    "default_consult_tariff_id": self.env["hms.tariff"].search(
                        [("code", "=", "KONS-UM" if specialty_code == "SPU" else "KONS-SP")],
                        limit=1,
                    ).id,
                })
            practitioners[name] = practitioner
        nurse_nik = 3273014501900001
        for index, (name, role) in enumerate(NURSES):
            practitioners[name] = self._get_or_create(
                "hms.practitioner", [("nik", "=", str(nurse_nik + index))], {
                    "name": name, "type": "nurse", "nik": str(nurse_nik + index),
                    "gender": "female" if index % 2 == 0 else "male",
                    "nurse_role": role, "nurse_level": "pk3",
                    "can_double_check_high_alert": role in ("charge_nurse", "head_nurse", "primary"),
                    "can_administer_iv": True, "can_take_blood_sample": True,
                    "str_no": f"STRP-{index + 1:05d}",
                    "str_valid_to": fields.Date.add(fields.Date.context_today(self), days=700),
                })
        pharmacist = self._get_or_create(
            "hms.practitioner", [("nik", "=", "3273010101850099")], {
                "name": "Nurul Aini", "title_prefix": "apt.", "type": "pharmacist",
                "nik": "3273010101850099", "gender": "female",
                "str_no": "STRA-00001",
                "str_valid_to": fields.Date.add(fields.Date.context_today(self), days=800),
            })
        # Indexed by name as well: the role-login builder looks practitioners
        # up by the name it is given, and a key that only exists under a slug
        # silently leaves the user unlinked.
        practitioners["apoteker"] = pharmacist
        practitioners[pharmacist.name] = pharmacist
        return practitioners

    def _wards(self):
        ranap = self.env["hms.unit"].search([("code", "=", "RANAP")], limit=1)
        classes = {c.code: c for c in self.env["hms.care.class"].search([])}
        wards = {}
        for ward_code, ward_name, ward_type, room_specs in WARDS:
            ward = self._get_or_create("hms.ward", [("code", "=", ward_code)], {
                "code": ward_code, "name": ward_name, "type": ward_type,
                "unit_id": ranap.id, "floor": "2", "building": "Gedung B",
            })
            wards[ward_code] = ward
            room_no = 1
            for class_code, bed_count in room_specs:
                per_room = 1 if class_code in ("VVIP", "VIP") else 2
                for _ in range(max(bed_count // per_room, 1)):
                    room_code = f"{ward_code}-{room_no:02d}"
                    room = self._get_or_create("hms.room", [("code", "=", room_code)], {
                        "code": room_code, "name": f"{ward_name} {room_no:02d}",
                        "ward_id": ward.id, "class_id": classes[class_code].id,
                        "capacity": per_room, "gender": "none",
                    })
                    for bed_index in range(per_room):
                        bed_code = f"{room_code}-{chr(65 + bed_index)}"
                        self._get_or_create("hms.bed", [("code", "=", bed_code)], {
                            "code": bed_code, "name": chr(65 + bed_index),
                            "room_id": room.id,
                            "has_oxygen": True,
                            "bed_type": "standard",
                        })
                    room_no += 1
        return wards

    def _depots(self):
        warehouse = self.env["stock.warehouse"].search([], limit=1)
        farmasi = self.env["hms.unit"].search([("code", "=", "FAR")], limit=1)
        for code, name, kind in (
            ("DEPO-RJ", "Depo Rawat Jalan", "outpatient"),
            ("DEPO-IGD", "Depo IGD", "emergency"),
            ("DEPO-RI", "Depo Rawat Inap", "inpatient"),
        ):
            self._get_or_create("hms.depot", [("code", "=", code)], {
                "code": code, "name": name, "type": kind,
                "unit_id": farmasi.id, "location_id": warehouse.lot_stock_id.id,
            })

    def _medicines(self):
        forms = {}
        for code, name, liquid in (
            ("TAB", "Tablet", False), ("KAP", "Kapsul", False), ("SIR", "Sirup", True),
            ("AMP", "Ampul", True), ("VIAL", "Vial", True), ("NEB", "Cairan Nebulizer", True),
            ("PEN", "Pen Injeksi", True), ("SAL", "Salep", False),
        ):
            forms[code] = self._get_or_create("hms.dosage.form", [("code", "=", code)], {
                "code": code, "name": name, "is_liquid": liquid,
            })
        routes = {}
        for code, name, parenteral in (
            ("oral", "Oral", False), ("iv", "Intravena", True), ("im", "Intramuskular", True),
            ("sc", "Subkutan", True), ("topical", "Topikal", False),
            ("inhalasi", "Inhalasi", False), ("rektal", "Rektal", False),
        ):
            routes[code] = self._get_or_create("hms.route", [("code", "=", code)], {
                "code": code, "name": name, "is_parenteral": parenteral,
            })
        frequencies = {}
        for code, name, per_day, times, prn in (
            ("1x1", "1 kali sehari", 1, "08:00", False),
            ("2x1", "2 kali sehari", 2, "08:00,20:00", False),
            ("3x1", "3 kali sehari", 3, "08:00,14:00,20:00", False),
            ("4x1", "4 kali sehari", 4, "06:00,12:00,18:00,00:00", False),
            ("q8h", "Setiap 8 jam", 3, "06:00,14:00,22:00", False),
            ("PRN", "Bila perlu", 0, "", True),
        ):
            frequencies[code] = self._get_or_create("hms.frequency", [("code", "=", code)], {
                "code": code, "name": name, "per_day": per_day, "times": times, "is_prn": prn,
            })

        Template = self.env["product.template"]
        Medicine = self.env["hms.medicine"]
        created = 0
        # The catalogue is the twenty real entries above, then brand variants
        # around them — enough breadth that search and formulary filters have
        # something to do, without inventing implausible drugs.
        brands = ["", "Generik", "Farma", "Medika", "Pharma", "Sehat", "Prima", "Utama",
                  "Husada", "Mitra"]
        for base_index, (generic, strength, form, route_codes, high_alert, narcotic, price) \
                in enumerate(MEDICINE_BASE):
            ingredient = self._get_or_create("hms.ingredient", [("name", "=", generic)], {
                "name": generic,
            })
            for brand_index, brand in enumerate(brands):
                name = f"{generic} {strength}" if not brand else f"{generic} {strength} ({brand})"
                if Medicine.search_count([("generic_name", "=", generic),
                                          ("brand_name", "=", brand or False)]):
                    continue
                template = Template.create({
                    "name": name,
                    "is_storable": True,
                    "tracking": "lot",
                    "use_expiration_date": True,
                    "list_price": price * (1 + brand_index * 0.05),
                    "standard_price": price * 0.7,
                })
                Medicine.create({
                    "product_tmpl_id": template.id,
                    "generic_name": generic,
                    "brand_name": brand or False,
                    "item_type": "drug",
                    "strength_display": strength,
                    "dosage_form_id": forms[form].id,
                    "route_ids": [(6, 0, [routes[r].id for r in route_codes])],
                    "is_high_alert": high_alert,
                    "is_narcotic": narcotic,
                    "is_psychotropic": generic in ("Diazepam",),
                    "is_generic": not brand,
                    "is_formularium_national": brand in ("", "Generik"),
                    "is_formularium_hospital": True,
                    "default_sig": "Sesudah makan" if "oral" in route_codes else "",
                    "default_frequency_id": frequencies["3x1"].id if "oral" in route_codes
                    else frequencies["1x1"].id,
                    "default_duration_days": 3,
                    "ingredient_ids": [(0, 0, {"ingredient_id": ingredient.id})],
                    "price_hna": price * 0.7,
                    "price_het": price * 1.2,
                })
                created += 1
        _logger.info("SIMRS demo: %s item obat dibuat", created)
        self._stock_medicines()

    def _stock_medicines(self):
        """Put stock on the shelf, with a spread of expiry dates so FEFO shows."""
        warehouse = self.env["stock.warehouse"].search([], limit=1)
        Quant = self.env["stock.quant"]
        Lot = self.env["stock.lot"]
        medicines = self.env["hms.medicine"].search([("item_type", "=", "drug")])
        today = fields.Datetime.now()
        for index, medicine in enumerate(medicines):
            if Quant.search_count([("product_id", "=", medicine.product_id.id)]):
                continue
            for lot_index, days in ((0, 120), (1, 540)):
                lot = Lot.create({
                    "name": f"LOT-{medicine.product_id.id}-{lot_index}",
                    "product_id": medicine.product_id.id,
                    "expiration_date": today + timedelta(days=days),
                })
                Quant.with_context(inventory_mode=True).create({
                    "product_id": medicine.product_id.id,
                    "location_id": warehouse.lot_stock_id.id,
                    "lot_id": lot.id,
                    "inventory_quantity": 200 if lot_index == 0 else 400,
                })._apply_inventory()

    def _payers(self):
        Partner = self.env["res.partner"]
        bpjs_partner = self._get_or_create("res.partner", [("name", "=", "BPJS Kesehatan")], {
            "name": "BPJS Kesehatan", "company_type": "company",
        })
        bpjs = self._get_or_create("hms.payer", [("code", "=", "BPJS")], {
            "code": "BPJS", "name": "BPJS Kesehatan", "type": "bpjs",
            "partner_id": bpjs_partner.id, "requires_sep": True, "sequence": 5,
        })
        classes = {c.code: c for c in self.env["hms.care.class"].search([])}
        for plan_code, plan_name, class_code in (
            ("PBI", "PBI — Kelas 3", "III"),
            ("NONPBI-2", "Non-PBI — Kelas 2", "II"),
            ("NONPBI-1", "Non-PBI — Kelas 1", "I"),
        ):
            self._get_or_create(
                "hms.payer.plan", [("payer_id", "=", bpjs.id), ("code", "=", plan_code)], {
                    "payer_id": bpjs.id, "code": plan_code, "name": plan_name,
                    "class_id": classes[class_code].id, "coverage_percent": 100.0,
                    "upgrade_class_rule": "pay_difference",
                })
        insurer_partner = self._get_or_create(
            "res.partner", [("name", "=", "Asuransi Sehat Sentosa")], {
                "name": "Asuransi Sehat Sentosa", "company_type": "company",
            })
        insurer = self._get_or_create("hms.payer", [("code", "=", "ASS")], {
            "code": "ASS", "name": "Asuransi Sehat Sentosa", "type": "insurance",
            "partner_id": insurer_partner.id, "requires_guarantee_letter": True, "sequence": 10,
        })
        self._get_or_create(
            "hms.payer.plan", [("payer_id", "=", insurer.id), ("code", "=", "GOLD")], {
                "payer_id": insurer.id, "code": "GOLD", "name": "Gold — Kelas I",
                "class_id": classes["I"].id, "coverage_percent": 80.0,
                "plafon_per_visit": 5000000,
            })

    # --- queue, schedules, nursing, cashier -------------------------------
    def _qms(self, units, practitioners):
        services = {}
        service_specs = [
            ("REG", "Pendaftaran", "A", "registration", None, 1),
            ("POLI-UMUM", "Poli Umum", "B", "clinic", "POLI-UMUM", 10),
            ("POLI-PD", "Poli Penyakit Dalam", "C", "clinic", "POLI-PD", 11),
            ("POLI-ANAK", "Poli Anak", "D", "clinic", "POLI-ANAK", 12),
            ("POLI-OBG", "Poli Kebidanan", "E", "clinic", "POLI-OBG", 13),
            ("POLI-BEDAH", "Poli Bedah", "F", "clinic", "POLI-BEDAH", 14),
            ("POLI-GIGI", "Poli Gigi", "G", "clinic", "POLI-GIGI", 15),
            ("LAB", "Laboratorium", "L", "lab", "LAB", 20),
            ("RAD", "Radiologi", "R", "radiology", "RAD", 21),
            ("FAR", "Apotek", "H", "pharmacy", "FAR", 30),
            ("KAS", "Kasir", "K", "cashier", None, 40),
        ]
        for code, name, prefix, kind, unit_code, sequence in service_specs:
            services[code] = self._get_or_create("hms.qms.service", [("code", "=", code)], {
                "code": code, "name": name, "prefix": prefix,
                "priority_prefix": f"P{prefix}", "kind": kind, "sequence": sequence,
                "unit_id": units[unit_code].id if unit_code else False,
                "display_label": name,
                "sla_minutes": 15 if kind == "registration" else 30,
                "priority_interleave": 3,
            })
        # Registration hands the patient on to the clinic queue; the clinical
        # flow issues pharmacy and cashier tickets on its own.
        services["REG"].write({"next_service_id": services["POLI-UMUM"].id})
        services["FAR"].write({"next_service_id": services["KAS"].id})

        counters = {}
        counter_specs = [
            ("LOKET-1", "Loket 1", ["REG"], "Lobi Utama", False),
            ("LOKET-2", "Loket 2", ["REG"], "Lobi Utama", False),
            ("PERIKSA-UM", "Ruang Periksa Umum", ["POLI-UMUM"], "Lantai 1", True),
            ("PERIKSA-PD", "Ruang Periksa Penyakit Dalam", ["POLI-PD"], "Lantai 1", True),
            ("PERIKSA-ANAK", "Ruang Periksa Anak", ["POLI-ANAK"], "Lantai 1", True),
            ("APOTEK-1", "Meja Apotek 1", ["FAR"], "Lantai 1", False),
            ("KASIR-1", "Kasir 1", ["KAS"], "Lobi Utama", False),
            ("KASIR-2", "Kasir 2", ["KAS"], "Lobi Utama", False),
        ]
        for code, name, service_codes, location, clinical in counter_specs:
            counters[code] = self._get_or_create("hms.qms.counter", [("code", "=", code)], {
                "code": code, "name": name, "location": location,
                "is_clinical": clinical,
                "service_ids": [(6, 0, [services[s].id for s in service_codes])],
            })

        printer = self._get_or_create("hms.qms.printer", [("name", "=", "Printer Kiosk Lobi")], {
            "name": "Printer Kiosk Lobi", "type": "browser", "paper_width_mm": "80",
        })
        self._get_or_create("hms.qms.kiosk", [("code", "=", "KIOSK-LOBI")], {
            "code": "KIOSK-LOBI", "name": "Kiosk Lobi Utama",
            "service_ids": [(6, 0, [services[c].id for c in
                                    ("REG", "POLI-UMUM", "POLI-PD", "POLI-ANAK", "LAB", "FAR")])],
            "printer_id": printer.id,
            "header_lines": f"{HOSPITAL}\nJl. Kesehatan Raya No. 1",
            "footer_lines": "Terima kasih. Perhatikan layar dan pengeras suara.",
        })

        display = self._get_or_create("hms.qms.display", [("code", "=", "TV-LOBI")], {
            "code": "TV-LOBI", "name": "TV Lobi Pendaftaran", "layout": "multi",
            "running_text": f"Selamat datang di {HOSPITAL} — mohon jaga jarak dan gunakan masker.",
        })
        if not display.zone_ids:
            self.env["hms.qms.display.zone"].create([
                {"display_id": display.id, "position": 1, "kind": "calling",
                 "title": "Sedang Dipanggil",
                 "counter_ids": [(6, 0, [counters["LOKET-1"].id, counters["LOKET-2"].id])],
                 "max_items": 4},
                {"display_id": display.id, "position": 2, "kind": "next_list",
                 "title": "Antrian Berikutnya",
                 "service_ids": [(6, 0, [services["REG"].id])], "max_items": 5},
                {"display_id": display.id, "position": 3, "kind": "stats",
                 "title": "Estimasi Menunggu",
                 "service_ids": [(6, 0, [services[c].id for c in
                                         ("REG", "POLI-UMUM", "FAR", "KAS")])]},
            ])
        poli_display = self._get_or_create("hms.qms.display", [("code", "=", "TV-POLI")], {
            "code": "TV-POLI", "name": "TV Koridor Poliklinik", "layout": "multi",
        })
        if not poli_display.zone_ids:
            self.env["hms.qms.display.zone"].create([{
                "display_id": poli_display.id, "position": 1, "kind": "calling",
                "title": "Poliklinik",
                "counter_ids": [(6, 0, [counters[c].id for c in
                                        ("PERIKSA-UM", "PERIKSA-PD", "PERIKSA-ANAK")])],
                "max_items": 3,
            }])
        return services

    def _schedules(self, units, practitioners):
        Template = self.env["hms.schedule.template"]
        clinic_by_specialty = {c[2]: c[0] for c in CLINICS}
        for name, specialty_code, _gender in DOCTORS:
            practitioner = practitioners.get(name)
            unit_code = clinic_by_specialty.get(specialty_code)
            if not (practitioner and unit_code):
                continue
            for weekday in ("0", "2", "4"):
                if Template.search_count([
                    ("practitioner_id", "=", practitioner.id), ("weekday", "=", weekday),
                ]):
                    continue
                Template.create({
                    "practitioner_id": practitioner.id,
                    "unit_id": units[unit_code].id,
                    "weekday": weekday,
                    "session": "morning",
                    "time_from": 8.0, "time_to": 12.0,
                    "slot_minutes": 15,
                    "quota_walkin": 10, "quota_booking": 4, "quota_bpjs": 6,
                })
        Template._cron_generate_slots(days_ahead=7)

    def _nursing(self, wards):
        for ward_code, ward in wards.items():
            self._get_or_create("hms.nursing.station", [("code", "=", f"NS-{ward_code}")], {
                "code": f"NS-{ward_code}", "name": f"Station {ward.name}",
                "type": "inpatient", "ward_id": ward.id,
                "nurse_ids": [(6, 0, self.env["hms.practitioner"].search(
                    [("type", "=", "nurse")], limit=4
                ).ids)],
            })
        igd = self.env["hms.unit"].search([("code", "=", "IGD")], limit=1)
        self._get_or_create("hms.nursing.station", [("code", "=", "NS-IGD")], {
            "code": "NS-IGD", "name": "Station IGD", "type": "emergency", "unit_id": igd.id,
        })

    def _nursing_masters(self):
        for code, name, category in (
            ("D.0077", "Nyeri Akut", "Kenyamanan"),
            ("D.0019", "Defisit Nutrisi", "Fisiologis"),
            ("D.0005", "Pola Napas Tidak Efektif", "Respirasi"),
            ("D.0009", "Perfusi Perifer Tidak Efektif", "Sirkulasi"),
            ("D.0130", "Hipertermia", "Termoregulasi"),
            ("D.0142", "Risiko Infeksi", "Keamanan"),
            ("D.0143", "Risiko Jatuh", "Keamanan"),
            ("D.0056", "Intoleransi Aktivitas", "Aktivitas"),
        ):
            self._get_or_create("hms.sdki", [("code", "=", code)], {
                "code": code, "name": name, "category": category,
            })
        for code, name in (
            ("L.08066", "Tingkat Nyeri"), ("L.03030", "Status Nutrisi"),
            ("L.01004", "Pola Napas"), ("L.02011", "Perfusi Perifer"),
            ("L.14134", "Termoregulasi"), ("L.14137", "Tingkat Infeksi"),
            ("L.14138", "Tingkat Jatuh"), ("L.05047", "Toleransi Aktivitas"),
        ):
            self._get_or_create("hms.slki", [("code", "=", code)], {"code": code, "name": name})
        for code, name in (
            ("I.08238", "Manajemen Nyeri"), ("I.03119", "Manajemen Nutrisi"),
            ("I.01011", "Manajemen Jalan Napas"), ("I.02079", "Perawatan Sirkulasi"),
            ("I.15506", "Manajemen Hipertermia"), ("I.14539", "Pencegahan Infeksi"),
            ("I.14540", "Pencegahan Jatuh"), ("I.05178", "Manajemen Energi"),
        ):
            self._get_or_create("hms.siki", [("code", "=", code)], {"code": code, "name": name})

    def _cashier(self):
        cash_journal = self.env["account.journal"].search([("type", "=", "cash")], limit=1)
        qms_counters = {c.code: c for c in self.env["hms.qms.counter"].search([])}
        for code, name, qms_code in (("KAS-1", "Kasir 1", "KASIR-1"),
                                     ("KAS-2", "Kasir 2", "KASIR-2")):
            self._get_or_create("hms.cashier.counter", [("code", "=", code)], {
                "code": code, "name": name,
                "qms_counter_id": qms_counters.get(qms_code).id if qms_counters.get(qms_code) else False,
                "journal_cash_id": cash_journal.id,
            })
        # Cost pools so the unit P&L demo has overhead to allocate.
        for name, driver in (("Listrik & Air", "area"), ("Manajemen & Administrasi", "visits"),
                             ("Teknologi Informasi", "headcount")):
            self._get_or_create("hms.cost.pool", [("name", "=", name)], {
                "name": name, "driver": driver,
            })
        # Doctor fee split: the hospital keeps 30% of the medical component.
        self._get_or_create("hms.medical.fee.rule", [("name", "=", "Bagi hasil jasa medis 70%")], {
            "name": "Bagi hasil jasa medis 70%", "percent": 70.0, "sequence": 50,
        })
        self.env["hms.unit"].search([("is_revenue_unit", "=", True)]).action_create_analytic_account()


    # --- role logins ------------------------------------------------------
    # Each frontline screen is meant to be shown as the person who uses it, so
    # the demo needs real logins rather than one administrator doing
    # everything. They also make the access rules visible: a cashier opening
    # the EMR menu is supposed to see nothing.
    # Nama grup boleh berupa nama pendek (diasumsikan milik custom_hms_base)
    # atau nama lengkap bermodul, karena peran casemix, rekam medis dan
    # keselamatan pasien hidup di modulnya masing-masing.
    DEMO_USERS = [
        ("dokter", "Andi Wijaya", ["group_hms_emr_clinician", "group_hms_registration_user"]),
        ("perawat", "Ani Rahayu", ["group_hms_nurse"]),
        ("apoteker", "Nurul Aini", ["group_hms_pharmacist"]),
        ("analis", "Lukman Hakim", ["group_hms_diagnostic_verifier"]),
        ("radiolog", "Kartika Sari", ["group_hms_diagnostic_verifier"]),
        # DPJP spesialis dengan akun sendiri. Bukan kemewahan: pengakuan nilai
        # kritis hanya boleh ditulis klinisi yang memang merawat pasiennya
        # (record rule hms.lab.result / hms.rad.report), sehingga DPJP tanpa
        # akun berarti lingkaran TBaK tidak pernah bisa ditutup di demo.
        ("dokter_pd", "Bambang Sutrisno", ["group_hms_emr_clinician"]),
        ("dokter_bedah", "Indra Kurniawan", ["group_hms_emr_clinician"]),
        ("dokter_anak", "Eko Prasetyo", ["group_hms_emr_clinician"]),
        ("pendaftaran", None, ["group_hms_registration_user"]),
        ("kasir", None, ["group_hms_cashier"]),
        ("manajer", None, ["group_hms_manager"]),
        ("koder", None, ["custom_hms_casemix.group_hms_coder"]),
        ("verifikator", None, ["custom_hms_casemix.group_hms_casemix_verifier"]),
        ("pmik", None, ["custom_hms_medrec.group_hms_medrec"]),
        ("kapmik", None, ["custom_hms_medrec.group_hms_medrec_manager",
                          "custom_hms_medrec.group_hms_medrec"]),
        ("kp", None, ["custom_hms_safety.group_hms_patient_safety"]),
    ]
    # Overridable so a demo on a shared host does not use a password that is
    # written down in the source tree.
    DEMO_PASSWORD = os.environ.get("SIMRS_DEMO_PASSWORD", "simrsdemo2026")

    @api.model
    def _group_ref(self, name):
        return self.env.ref(name if "." in name else f"custom_hms_base.{name}")

    @api.model
    def _users(self, practitioners):
        Users = self.env["res.users"].sudo()
        created = {}
        for slug, practitioner_name, groups in self.DEMO_USERS:
            login = f"{slug}@simrs-demo.invalid"
            user = Users.search([("login", "=", login)], limit=1)
            if not user:
                user = Users.create({
                    "name": practitioner_name or slug.capitalize(),
                    "login": login,
                    "password": self.DEMO_PASSWORD,
                    "group_ids": [(4, self._group_ref(g).id) for g in groups],
                })
            practitioner = practitioners.get(practitioner_name) if practitioner_name else None
            if practitioner and not practitioner.user_id:
                practitioner.write({"user_id": user.id})
            created[slug] = user
        return created

    @api.model
    def demo_user(self, slug):
        return self.env["res.users"].sudo().search(
            [("login", "=", f"{slug}@simrs-demo.invalid")], limit=1
        )

    # --- patients ---------------------------------------------------------
    def _patients(self, count=50):
        Patient = self.env["hms.patient"]
        existing = Patient.search_count([])
        if existing >= count:
            return Patient
        payers = {p.code: p for p in self.env["hms.payer"].search([])}
        allergens = self.env["hms.ingredient"].search([], limit=6)
        created = Patient
        base_nik = 3273010101000000
        for index in range(count - existing):
            gender = "male" if index % 2 == 0 else "female"
            first = random.choice(FIRST_NAMES_M if gender == "male" else FIRST_NAMES_F)
            name = f"{first} {random.choice(LAST_NAMES)}"
            age = random.choice([2, 5, 9, 17, 24, 31, 38, 45, 52, 60, 67, 74])
            birth = fields.Date.subtract(
                fields.Date.context_today(self), days=age * 365 + random.randint(0, 364)
            )
            payer_code = random.choices(["BPJS", "UMUM", "ASS"], weights=[6, 3, 1])[0]
            payer = payers.get(payer_code)
            vals = {
                "name": name,
                "nik": str(base_nik + 100000 + existing + index),
                "birth_date": birth,
                "gender": gender,
                "phone": f"08{random.randint(1000000000, 9999999999)}",
                "address_street": f"Jl. {random.choice(LAST_NAMES)} No. {random.randint(1, 200)}",
                "default_payer_id": payer.id if payer else False,
                "marital_status": "married" if age > 25 else "single",
                "blood_type": random.choice(["a", "b", "ab", "o"]),
            }
            if payer_code == "BPJS":
                vals["bpjs_no"] = f"000{random.randint(1000000000, 9999999999)}"
                vals["bpjs_class"] = random.choice(["1", "2", "3"])
            patient = Patient.create(vals)
            # One patient in six carries a recorded allergy, which is roughly
            # what a real register looks like and enough for the screening
            # demo to fire without every prescription turning red.
            if index % 6 == 0 and allergens:
                allergen = random.choice(allergens)
                self.env["hms.patient.allergy"].create({
                    "patient_id": patient.id,
                    "substance": allergen.name,
                    "ingredient_id": allergen.id,
                    "substance_type": "drug",
                    "severity": random.choice(["mild", "moderate", "severe"]),
                    "reaction": random.choice(["Gatal dan ruam", "Bengkak wajah", "Sesak napas"]),
                })
            created |= patient
        _logger.info("SIMRS demo: %s pasien dibuat", len(created))
        return created


class HmsDemoScenario(models.AbstractModel):
    """Runnable demo journeys.

    These are the scripts a presenter follows, executed by code so that the
    state the demo starts from is identical every time — and so that the same
    sequence doubles as an integration check across every module.
    """
    _name = "hms.demo.scenario"
    _description = "Skenario Demo SIMRS"

    def _as(self, slug):
        """Return self acting as the demo user for a role, when one exists."""
        user = self.env["hms.demo.builder"].demo_user(slug)
        return self.with_user(user) if user else self

    def _pick(self, model, domain, message):
        record = self.env[model].search(domain, limit=1)
        if not record:
            raise UserError(message)
        return record

    @api.model
    def run_outpatient(self, payer_code="UMUM"):
        """Walk-in → queue → clinic → prescription → pharmacy → cashier."""
        Ticket = self.env["hms.qms.ticket"]
        unit = self._pick("hms.unit", [("code", "=", "POLI-UMUM")], _("Poli Umum belum ada."))
        payer = self._pick("hms.payer", [("code", "=", payer_code)], _("Penjamin belum ada."))
        doctor = self._pick(
            "hms.practitioner", [("type", "=", "doctor"), ("unit_ids", "in", unit.id)],
            _("Dokter poli umum belum ada."),
        )
        patient = self._pick(
            "hms.patient",
            [("default_payer_id", "=", payer.id), ("state", "=", "active")],
            _("Pasien demo belum ada."),
        )
        steps = []

        encounter = self.env["hms.encounter"].create({
            "patient_id": patient.id, "unit_id": unit.id,
            "practitioner_id": doctor.id, "payer_id": payer.id,
            "payer_plan_id": payer.plan_ids[:1].id,
            "chief_complaint": "Demam dan batuk sejak 3 hari",
        })
        steps.append(("Pendaftaran", f"{encounter.name} untuk {patient.name}"))
        ticket = encounter.current_ticket_id
        if ticket:
            steps.append(("Tiket antrian", ticket.name))
            counter = self.env["hms.qms.counter"].search(
                [("service_ids", "=", ticket.service_id.id)], limit=1
            )
            if counter:
                if counter.state != "open":
                    counter.action_open()
                ticket.action_call(counter)
                ticket.action_serve()
                steps.append(("Dipanggil", f"{ticket.name} ke {counter.name}"))

        self.env["hms.observation"].create({
            "encounter_id": encounter.id, "context": "initial",
            "systolic": 118, "diastolic": 76, "pulse": 92, "respiratory_rate": 20,
            "temperature": 38.4, "spo2": 97, "weight_kg": 62, "height_cm": 167,
            "pain_score": 3,
        })
        steps.append(("TTV", "TD 118/76, nadi 92, suhu 38,4 °C"))

        note = self.env["hms.clinical.note"].create({
            "encounter_id": encounter.id, "author_id": doctor.id, "author_role": "doctor",
            "note_type": "soap",
            "subjective": "Demam naik turun 3 hari, batuk berdahak, nafsu makan menurun.",
            "objective": "Kesadaran compos mentis, faring hiperemis, rhonki tidak ada.",
            "assessment": "Observasi febris hari ke-3, suspek infeksi saluran napas atas.",
            "plan": "Cek darah lengkap, antipiretik, antibiotik bila leukositosis.",
        })
        note.action_sign()
        steps.append(("CPPT", "SOAP ditandatangani dokter"))

        icd = self.env["hms.icd10"].search([("code", "like", "J06")], limit=1) or \
            self.env["hms.icd10"].create({
                "code": "J06.9", "name_en": "Acute upper respiratory infection, unspecified",
                "name_id": "Infeksi saluran napas atas akut",
            })
        self.env["hms.diagnosis"].create({
            "encounter_id": encounter.id, "icd10_id": icd.id,
            "rank": "primary", "stage": "working", "practitioner_id": doctor.id,
        })
        steps.append(("Diagnosis", f"{icd.code} — {icd.display_name}"))

        lab_tariff = self._pick("hms.tariff", [("code", "=", "LAB-DL")], _("Tarif lab belum ada."))
        lab_order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "lab",
            "practitioner_id": doctor.id,
            "target_unit_id": lab_tariff.unit_id.id,
            "clinical_note": "Observasi febris, singkirkan demam berdarah.",
            "line_ids": [(0, 0, {"tariff_id": lab_tariff.id})],
        })
        lab_order.action_submit()
        lab_order.line_ids.action_start()
        analyst = self.env["hms.demo.builder"].demo_user("analis")
        for result in lab_order.line_ids.lab_result_ids:
            value = {"HB": 13.5, "WBC": 13.2, "PLT": 180.0, "HCT": 41.0}.get(
                result.parameter_id.code, 10.0
            )
            result.write({"value_numeric": value})
            # Entry, validation and verification are recorded against the
            # analyst, not against whoever triggered the scenario.
            actor = result.with_user(analyst) if analyst else result
            actor.action_enter()
            actor.action_validate()
            actor.action_verify()
        steps.append(("Laboratorium", "Darah lengkap terverifikasi — leukosit 13,2 (tinggi)"))

        depot = self._pick("hms.depot", [("code", "=", "DEPO-RJ")], _("Depo rawat jalan belum ada."))
        paracetamol = self._pick(
            "hms.medicine", [("generic_name", "=", "Parasetamol"), ("brand_name", "=", False)],
            _("Obat demo belum ada."),
        )
        amoxicillin = self._pick(
            "hms.medicine", [("generic_name", "=", "Amoksisilin"), ("brand_name", "=", False)],
            _("Obat demo belum ada."),
        )
        frequency = self.env["hms.frequency"].search([("code", "=", "3x1")], limit=1)
        oral = self.env["hms.route"].search([("code", "=", "oral")], limit=1)
        prescription = self.env["hms.prescription"].create({
            "encounter_id": encounter.id, "practitioner_id": doctor.id, "depot_id": depot.id,
            "line_ids": [
                (0, 0, {"medicine_id": paracetamol.id, "dose": 500, "dose_unit": "mg",
                        "frequency_id": frequency.id, "route_id": oral.id,
                        "duration_days": 3, "qty_prescribed": 9, "sig": "3x1 sesudah makan"}),
                (0, 0, {"medicine_id": amoxicillin.id, "dose": 500, "dose_unit": "mg",
                        "frequency_id": frequency.id, "route_id": oral.id,
                        "duration_days": 5, "qty_prescribed": 15, "sig": "3x1 sesudah makan"}),
            ],
        })
        prescription.action_submit()
        steps.append(("E-resep", f"{prescription.name} masuk antrian apotek"))
        pharmacist_user = self.env["hms.demo.builder"].demo_user("apoteker")
        rx_actor = prescription.with_user(pharmacist_user) if pharmacist_user else prescription
        rx_actor.action_verify()
        rx_actor.action_prepare()
        rx_actor.action_ready()
        rx_actor.action_dispense()
        steps.append(("Apotek", f"Obat diserahkan, stok dipotong lewat {prescription.picking_id.name}"))

        encounter.action_close()
        steps.append(("Kunjungan", "Ditutup, tagihan siap"))

        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)], limit=1)
        if bill and bill.state == "draft" and not bill.unpriced_line_count:
            bill.action_open()
            steps.append(("Tagihan", f"{bill.name} — total {bill.amount_total:,.0f}, "
                                     f"pasien {bill.amount_patient:,.0f}"))
        return {"encounter_id": encounter.id, "bill_id": bill.id if bill else None,
                "steps": steps}

    @api.model
    def run_inpatient(self):
        """Emergency triage → admission → daily charges → discharge readiness."""
        igd = self._pick("hms.unit", [("code", "=", "IGD")], _("IGD belum ada."))
        payer = self._pick("hms.payer", [("code", "=", "BPJS")], _("Penjamin BPJS belum ada."))
        doctor = self._pick("hms.practitioner", [("can_be_dpjp", "=", True)],
                            _("DPJP belum ada."))
        bed = self._pick("hms.bed", [("state", "=", "vacant")], _("Tidak ada bed kosong."))
        patient = self._pick(
            "hms.patient", [("bpjs_no", "!=", False), ("state", "=", "active")],
            _("Pasien BPJS demo belum ada."),
        )
        steps = []
        encounter = self.env["hms.encounter"].create({
            "patient_id": patient.id, "unit_id": igd.id, "type": "emergency",
            "practitioner_id": doctor.id, "payer_id": payer.id,
            "payer_plan_id": payer.plan_ids[:1].id,
            "triage_level": "yellow", "triage_at": fields.Datetime.now(),
            "arrival_mode": "ambulance",
            "chief_complaint": "Nyeri perut kanan bawah hebat sejak 6 jam",
        })
        steps.append(("IGD", f"{encounter.name} triase kuning"))
        admission = self.env["hms.admission"].admit(
            encounter, bed, doctor,
            entitled_class=payer.plan_ids[:1].class_id, source="emergency",
        )
        steps.append(("Admisi", f"{admission.name} di bed {bed.code} ({admission.class_id.name})"))
        self.env["hms.observation"].create({
            "encounter_id": encounter.id, "context": "initial",
            "systolic": 105, "diastolic": 68, "pulse": 104, "respiratory_rate": 22,
            "temperature": 38.1, "spo2": 96, "pain_score": 7,
        })
        steps.append(("TTV + EWS", "Skor dihitung otomatis dan dieskalasi bila perlu"))
        note = self.env["hms.clinical.note"].create({
            "encounter_id": encounter.id, "author_id": doctor.id, "author_role": "doctor",
            "note_type": "medical_initial",
            "subjective": "Nyeri perut kanan bawah, mual, tidak nafsu makan.",
            "objective": "Nyeri tekan McBurney positif, rebound tenderness positif.",
            "assessment": "Suspek apendisitis akut.",
            "plan": "Puasakan, infus RL, konsul bedah, siapkan laparotomi.",
            "instruction": "Pasang infus RL 20 tpm, pasien dipuasakan.",
        })
        note.action_sign()
        steps.append(("CPPT + instruksi", "Instruksi dokter menjadi tugas keperawatan"))
        charges = admission._generate_daily_charges(fields.Date.context_today(self))
        steps.append(("Charge harian", f"{len(charges)} baris (kamar, keperawatan, visite)"))
        blockers = admission.discharge_check()
        steps.append(("Cek pulang", f"{len(blockers)} hal masih menahan pemulangan"))
        return {"admission_id": admission.id, "encounter_id": encounter.id,
                "steps": steps, "blockers": blockers}
