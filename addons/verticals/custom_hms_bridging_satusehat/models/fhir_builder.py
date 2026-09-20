# -*- coding: utf-8 -*-
"""SIMRS records → FHIR R4 resources.

Pure functions over recordsets: no HTTP, no state. That makes the mapping
testable on its own, which matters because a wrong mapping is only visible as a
rejection from Kemenkes days later.
"""
from odoo import models

SYSTEM_NIK = "https://fhir.kemkes.go.id/id/nik"
SYSTEM_MRN = "http://sys-ids.kemkes.go.id/patient"
SYSTEM_ICD10 = "http://hl7.org/fhir/sid/icd-10"
SYSTEM_LOINC = "http://loinc.org"
SYSTEM_KFA = "http://sys-ids.kemkes.go.id/kfa"

GENDER_MAP = {"male": "male", "female": "female"}
ENCOUNTER_CLASS = {
    "outpatient": ("AMB", "ambulatory"),
    "emergency": ("EMER", "emergency"),
    "inpatient": ("IMP", "inpatient encounter"),
    "daycare": ("AMB", "ambulatory"),
    "mcu": ("AMB", "ambulatory"),
    "telemedicine": ("VR", "virtual"),
}
ENCOUNTER_STATUS = {
    "registered": "arrived",
    "in_progress": "in-progress",
    "admitted": "in-progress",
    "finished": "finished",
    "discharged": "finished",
    "cancelled": "cancelled",
}


class HmsFhirBuilder(models.AbstractModel):
    _name = "hms.fhir.builder"
    _description = "Pembangun Resource FHIR"

    def patient_resource(self, patient):
        """FHIR Patient. NIK is the national identifier Kemenkes matches on."""
        identifiers = []
        if patient.nik:
            identifiers.append({"system": SYSTEM_NIK, "use": "official", "value": patient.nik})
        if patient.mrn:
            identifiers.append({"system": SYSTEM_MRN, "use": "usual", "value": patient.mrn})
        resource = {
            "resourceType": "Patient",
            "identifier": identifiers,
            "active": patient.state == "active",
            "name": [{"use": "official", "text": patient.name}],
            "gender": GENDER_MAP.get(patient.gender, "unknown"),
            "birthDate": str(patient.birth_date) if patient.birth_date else None,
        }
        if patient.phone:
            resource["telecom"] = [{"system": "phone", "value": patient.phone, "use": "mobile"}]
        if patient.address_street:
            resource["address"] = [{
                "use": "home", "line": [patient.address_street],
                "city": patient.city_id.name or "", "postalCode": patient.postal_code or "",
                "country": "ID",
            }]
        if patient.ihs_patient_id:
            resource["id"] = patient.ihs_patient_id
        return {k: v for k, v in resource.items() if v not in (None, [], "")}

    def encounter_resource(self, encounter, org_id):
        code, display = ENCOUNTER_CLASS.get(encounter.type, ("AMB", "ambulatory"))
        resource = {
            "resourceType": "Encounter",
            "status": ENCOUNTER_STATUS.get(encounter.state, "unknown"),
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": code, "display": display,
            },
            "subject": {
                "reference": f"Patient/{encounter.patient_id.ihs_patient_id}",
                "display": encounter.patient_id.name,
            },
            "participant": [{
                "type": [{"coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                    "code": "ATND", "display": "attender",
                }]}],
                "individual": {
                    "reference": f"Practitioner/{encounter.practitioner_id.ihs_practitioner_id}",
                    "display": encounter.practitioner_id.display_name,
                },
            }] if encounter.practitioner_id.ihs_practitioner_id else [],
            "period": {"start": _iso(encounter.arrival_at)},
            "serviceProvider": {"reference": f"Organization/{org_id}"},
            "identifier": [{
                "system": f"http://sys-ids.kemkes.go.id/encounter/{org_id}",
                "value": encounter.name,
            }],
        }
        if encounter.closed_at:
            resource["period"]["end"] = _iso(encounter.closed_at)
        if encounter.ihs_encounter_id:
            resource["id"] = encounter.ihs_encounter_id
        if encounter.unit_id.ihs_location_id:
            resource["location"] = [{"location": {
                "reference": f"Location/{encounter.unit_id.ihs_location_id}",
                "display": encounter.unit_id.name,
            }}]
        return {k: v for k, v in resource.items() if v not in (None, [], "")}

    def condition_resource(self, diagnosis):
        category = "encounter-diagnosis"
        resource = {
            "resourceType": "Condition",
            "clinicalStatus": {"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                "code": "active", "display": "Active",
            }]},
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                "code": category, "display": "Encounter Diagnosis",
            }]}],
            "code": {"coding": [{
                "system": SYSTEM_ICD10,
                "code": diagnosis.icd10_id.code,
                "display": diagnosis.icd10_id.name_en or diagnosis.icd10_id.name_id,
            }]},
            "subject": {
                "reference": f"Patient/{diagnosis.patient_id.ihs_patient_id}",
                "display": diagnosis.patient_id.name,
            },
            "encounter": {
                "reference": f"Encounter/{diagnosis.encounter_id.ihs_encounter_id}",
            },
            "recordedDate": _iso(diagnosis.diagnosed_at),
        }
        if diagnosis.ihs_condition_id:
            resource["id"] = diagnosis.ihs_condition_id
        return resource

    def observation_resources(self, observation):
        """One FHIR Observation per vital sign that was actually recorded.

        FHIR models each measurement separately; bundling them into one
        resource is the most common reason a vitals push is rejected.
        """
        vitals = [
            ("8480-6", "Systolic blood pressure", observation.systolic, "mm[Hg]"),
            ("8462-4", "Diastolic blood pressure", observation.diastolic, "mm[Hg]"),
            ("8867-4", "Heart rate", observation.pulse, "/min"),
            ("9279-1", "Respiratory rate", observation.respiratory_rate, "/min"),
            ("8310-5", "Body temperature", observation.temperature, "Cel"),
            ("59408-5", "Oxygen saturation", observation.spo2, "%"),
            ("29463-7", "Body weight", observation.weight_kg, "kg"),
            ("8302-2", "Body height", observation.height_cm, "cm"),
        ]
        out = []
        for code, display, value, unit in vitals:
            if not value:
                continue
            out.append({
                "resourceType": "Observation",
                "status": "final",
                "category": [{"coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "vital-signs", "display": "Vital Signs",
                }]}],
                "code": {"coding": [{"system": SYSTEM_LOINC, "code": code, "display": display}]},
                "subject": {
                    "reference": f"Patient/{observation.patient_id.ihs_patient_id}",
                },
                "encounter": {
                    "reference": f"Encounter/{observation.encounter_id.ihs_encounter_id}",
                },
                "effectiveDateTime": _iso(observation.taken_at),
                "valueQuantity": {
                    "value": value, "unit": unit,
                    "system": "http://unitsofmeasure.org", "code": unit,
                },
            })
        return out

    def medication_request_resource(self, line, org_id):
        rx = line.prescription_id
        return {
            "resourceType": "MedicationRequest",
            "status": "completed" if line.state == "dispensed" else "active",
            "intent": "order",
            "medicationCodeableConcept": {"coding": [{
                "system": SYSTEM_KFA,
                "code": line.medicine_id.kfa_code or "",
                "display": line.medicine_id.display_name,
            }]},
            "subject": {"reference": f"Patient/{rx.patient_id.ihs_patient_id}"},
            "encounter": {"reference": f"Encounter/{rx.encounter_id.ihs_encounter_id}"},
            "authoredOn": _iso(rx.prescribed_at),
            "requester": {
                "reference": f"Practitioner/{rx.practitioner_id.ihs_practitioner_id}",
                "display": rx.practitioner_id.display_name,
            },
            "dosageInstruction": [{
                "text": line.sig or "",
                "route": {"coding": [{"display": line.route_id.name or ""}]},
            }],
            "dispenseRequest": {
                "quantity": {"value": line.qty_prescribed, "unit": "unit"},
            },
            "identifier": [{
                "system": f"http://sys-ids.kemkes.go.id/prescription/{org_id}",
                "value": f"{rx.name}-{line.id}",
            }],
        }


def _iso(value):
    """FHIR wants an ISO-8601 instant with an offset; SIMRS stores naive UTC."""
    return f"{value.isoformat()}+00:00" if value else None
