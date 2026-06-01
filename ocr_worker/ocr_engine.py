import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract
from dotenv import load_dotenv
from pdf2image import convert_from_path
from rapidfuzz import fuzz

load_dotenv()

TESSERACT_CMD = os.getenv("TESSERACT_CMD")
POPPLER_PATH = os.getenv("POPPLER_PATH") or None
PDF_DPI = int(os.getenv("OCR_PDF_DPI", "400"))

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


KTP_FIELDS = [
    "nik",
    "nama",
    "tempat_lahir",
    "tanggal_lahir",
    "jenis_kelamin",
    "golongan_darah",
    "alamat",
    "rt_rw",
    "kel_desa",
    "kecamatan",
    "agama",
    "status_perkawinan",
    "pekerjaan",
    "tanggal_penerbitan",
    "kewarganegaraan",
    "berlaku_hingga",
]

NPWP_FIELDS = [
    "npwp",
    "npwp15",
    "npwp16",
    "nama",
    "alamat",
    "terdaftar",
    "kpp",
]


# ============================================================
# Generic helpers
# ============================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\x0c", "")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_line(line: str) -> str:
    if not line:
        return ""

    line = str(line).strip()
    line = line.replace("|", "I")
    line = line.replace(">", ":")
    line = line.replace("=", ":")
    line = line.replace(";", ":")
    line = re.sub(r"[ \t]+", " ", line)
    return line.strip()


def normalize_value(value: Any) -> str | None:
    if value is None:
        return None

    value = normalize_line(str(value))
    value = re.sub(r"^[\s:;,.=_\-]+", "", value)
    value = re.sub(r"[\s:;,.=_\-]+$", "", value)
    value = re.sub(r"\s+", " ", value)
    value = value.upper().strip()

    return value or None


def text_lines(text: str) -> list[str]:
    return [normalize_line(x) for x in clean_text(text).splitlines() if normalize_line(x)]


def alpha_key(text: str) -> str:
    text = str(text).upper()
    text = text.replace("0", "O").replace("1", "I").replace("!", "I").replace("|", "I")
    text = re.sub(r"[^A-Z]", "", text)
    return text


def repair_digit_text(value: str) -> str:
    table = str.maketrans({
        "O": "0", "o": "0", "Q": "0", "D": "0",
        "I": "1", "l": "1", "|": "1", "!": "1",
        "S": "5", "s": "5",
        "B": "8",
        "G": "6",
        "Z": "2", "z": "2",
    })
    return str(value).translate(table)


def extract_date(value: str | None) -> str | None:
    if not value:
        return None

    repaired = repair_digit_text(str(value))
    match = re.search(r"\b(\d{1,2})[-/.]\s*(\d{1,2})[-/.]\s*(\d{4})\b", repaired)
    if not match:
        return None

    day, month, year = match.groups()
    day_i = int(day)
    month_i = int(month)
    year_i = int(year)

    if not (1 <= day_i <= 31 and 1 <= month_i <= 12 and 1900 <= year_i <= 2100):
        return None

    return f"{day_i:02d}-{month_i:02d}-{year_i}"


def is_valid_date(value: Any) -> bool:
    return extract_date(str(value)) is not None if value else False


def find_labeled_value(text: str, label_patterns: list[str]) -> str | None:
    """
    Strict line-based label extraction.
    This avoids the previous bug where fuzzy matching selected nearby wrong lines,
    for example Nama becoming Alamat/Dusun.
    """
    for line in text_lines(text):
        upper = normalize_line(line).upper()

        for label_pattern in label_patterns:
            pattern = rf"^\s*(?:{label_pattern})\s*[:.\-_/\\ ]*\s*(.+?)\s*$"
            match = re.search(pattern, upper, flags=re.IGNORECASE)
            if match:
                value = normalize_value(match.group(1))
                if value:
                    return value

    return None


def stop_at_next_label(value: str | None) -> str | None:
    value = normalize_value(value)
    if not value:
        return None

    stop_patterns = [
        r"\bNIK\b",
        r"\bNAMA\b",
        r"\bNAME\b",
        r"\bTEMPAT\b",
        r"\bJENIS\b",
        r"\bGOL\.?\s*DARAH\b",
        r"\bALAMAT\b",
        r"\bRT\s*/\s*RW\b",
        r"\bKEL\s*/?\s*DESA\b",
        r"\bKECAMATAN\b",
        r"\bAGAMA\b",
        r"\bSTATUS\b",
        r"\bPEKERJAAN\b",
        r"\bKEWARGANEGARAAN\b",
        r"\bBERLAKU\b",
    ]

    cut = len(value)
    for pattern in stop_patterns:
        match = re.search(pattern, value)
        if match and match.start() > 0:
            cut = min(cut, match.start())

    return normalize_value(value[:cut])


def clean_words(value: str | None, min_len: int = 3) -> str | None:
    value = normalize_value(value)
    if not value:
        return None

    value = re.sub(r"[^A-Z0-9\s.'/-]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) >= min_len else None


def clean_person_name(value: str | None) -> str | None:
    value = stop_at_next_label(value)
    if not value:
        return None

    value = re.sub(r"[^A-Z\s.'-]", " ", value)
    value = re.sub(r"\b(NIK|NAMA|NAME|ALAMAT|TEMPAT|TGL|LAHIR|PROVINSI|KABUPATEN)\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    if len(value) < 3:
        return None

    return value


# ============================================================
# Document detection
# ============================================================

def get_ktp_nik(text: str) -> str | None:
    # Prefer NIK-labeled segment.
    patterns = [
        r"N[\s\W]*I[\s\W]*K[\s:;=._\-]*([0-9A-Za-z\s|!]{14,28})",
        r"\bNIK\b[\s:;=._\-]*([0-9A-Za-z\s|!]{14,28})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        digits = re.sub(r"\D", "", repair_digit_text(match.group(1)))
        if len(digits) >= 16:
            return digits[:16]

    # Fallback: any clear 16 digit sequence.
    match = re.search(r"\b\d{16}\b", text)
    if match:
        return match.group(0)

    return None


def get_npwp15(text: str) -> str | None:
    patterns = [
        r"\b(\d{2}[.\- ]?\d{3}[.\- ]?\d{3}[.\- ]?\d{1}[.\- ]?\d{3}[.\- ]?\d{3})\b",
        r"NPWP[\s:;=._\-]*([0-9.\- ]{15,25})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        digits = re.sub(r"\D", "", match.group(1))
        if len(digits) == 15:
            return digits

    return None


def get_npwp16(text: str) -> str | None:
    patterns = [
        r"NPWP\s*16[\s:;=._\-]*([0-9A-Za-z\s|!]{14,24})",
        r"\b(\d{16})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        digits = re.sub(r"\D", "", repair_digit_text(match.group(1)))
        if len(digits) == 16:
            return digits

    return None


def detect_document_type(text: str) -> str:
    upper = text.upper()

    ktp_score = 0
    npwp_score = 0

    if get_ktp_nik(text):
        ktp_score += 5

    if get_npwp15(text) or ("NPWP" in upper and get_npwp16(text)):
        npwp_score += 5

    for keyword in ["PROVINSI", "KABUPATEN", "KOTA", "KARTU TANDA PENDUDUK", "NIK", "KECAMATAN", "BERLAKU"]:
        if keyword in upper:
            ktp_score += 1

    for keyword in ["NPWP", "KPP", "PAJAK", "TERDAFTAR", "WAJIB PAJAK"]:
        if keyword in upper:
            npwp_score += 1

    # Light fuzzy rescue. Do not overdo it or random noisy text becomes KTP.
    for line in text_lines(text):
        key = alpha_key(line)
        if fuzz.partial_ratio("PROVINSI", key) >= 82:
            ktp_score += 1
        if fuzz.partial_ratio("KABUPATEN", key) >= 82:
            ktp_score += 1
        if fuzz.partial_ratio("KECAMATAN", key) >= 82:
            ktp_score += 1
        if fuzz.partial_ratio("NPWP", key) >= 85:
            npwp_score += 2

    if npwp_score >= 3 and npwp_score > ktp_score:
        return "NPWP"

    if ktp_score >= 2:
        return "KTP"

    return "UNKNOWN"


# ============================================================
# KTP extraction
# ============================================================

def split_birth_place_date(value: str | None) -> tuple[str | None, str | None]:
    value = normalize_value(value)
    if not value:
        return None, None

    date = extract_date(value)
    if not date:
        return clean_words(value), None

    match = re.search(r"\d{1,2}[-/.]\s*\d{1,2}[-/.]\s*\d{4}", repair_digit_text(value))
    tempat = value[:match.start()] if match else value
    tempat = tempat.replace(",", " ")
    tempat = re.sub(r"[^A-Z\s.'-]", " ", tempat)
    tempat = re.sub(r"\s+", " ", tempat).strip()

    return (tempat if len(tempat) >= 3 else None), date


def normalize_gender(value: str | None) -> str | None:
    value = normalize_value(value)
    if not value:
        return None

    key = alpha_key(value)

    if "LAKILAKI" in key or "LAKI" in key or fuzz.partial_ratio("LAKILAKI", key) >= 75:
        return "LAKI-LAKI"

    if "PEREMPUAN" in key or "WANITA" in key or fuzz.partial_ratio("PEREMPUAN", key) >= 78:
        return "PEREMPUAN"

    return None


def normalize_religion(value: str | None) -> str | None:
    value = normalize_value(value)
    if not value:
        return None

    key = alpha_key(value)
    known = ["ISLAM", "KRISTEN", "KATOLIK", "HINDU", "BUDDHA", "KONGHUCU"]

    for item in known:
        if item in key or fuzz.partial_ratio(item, key) >= 82:
            return item

    return None


def normalize_marital(value: str | None) -> str | None:
    value = normalize_value(value)
    if not value:
        return None

    key = alpha_key(value)

    if "BELUM" in key and "KAWIN" in key:
        return "BELUM KAWIN"

    if "KAWIN" in key or fuzz.partial_ratio("KAWIN", key) >= 82:
        return "KAWIN"

    if "CERAIHIDUP" in key:
        return "CERAI HIDUP"

    if "CERAIMATI" in key:
        return "CERAI MATI"

    return None


def normalize_blood_type(value: str | None) -> str | None:
    value = normalize_value(value)
    if not value:
        return None

    value = value.replace("0", "O")
    if value in ["-", "--"]:
        return None

    match = re.search(r"\b(AB|A|B|O)\b", value)
    return match.group(1) if match else None


def normalize_valid_until(value: str | None) -> str | None:
    value = normalize_value(value)
    if not value:
        return None

    key = alpha_key(value)

    if "SEUMURHIDUP" in key or fuzz.partial_ratio("SEUMURHIDUP", key) >= 74:
        return "SEUMUR HIDUP"

    return extract_date(value)


def extract_rt_rw(text: str) -> str | None:
    patterns = [
        r"(?:RT\s*/\s*RW|RT\s*RW|RTRW|RTEW|RREW)[\s:;=._\-]*([0-9OIl|!]{1,3})\s*/\s*([0-9OIl|!]{1,3})",
        r"\b([0-9OIl|!]{1,3})\s*/\s*([0-9OIl|!]{1,3})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        left = re.sub(r"\D", "", repair_digit_text(match.group(1)))
        right = re.sub(r"\D", "", repair_digit_text(match.group(2)))

        if left and right:
            return f"{int(left):03d}/{int(right):03d}"

    return None


def extract_ktp_fields(text: str) -> dict[str, Any]:
    raw = clean_text(text)

    nik = get_ktp_nik(raw)

    nama = find_labeled_value(raw, [
        r"NAMA",
        r"NAME",
    ])
    nama = clean_person_name(nama)

    ttl = find_labeled_value(raw, [
        r"TEMPAT\s*/?\s*TGL\.?\s*LAHIR",
        r"TEMPAT\s*TGL\.?\s*LAHIR",
        r"TEMPATI?\s*TG[LI!1]?\s*LAHIR",
        r"TEMPAT.*LAHIR",
    ])
    tempat_lahir, tanggal_lahir = split_birth_place_date(ttl)

    jenis_kelamin_raw = find_labeled_value(raw, [
        r"JENIS\s*KELAMIN",
    ])
    jenis_kelamin = normalize_gender(jenis_kelamin_raw)

    # Sometimes gender and blood type are on one line.
    golongan_darah = None
    gol_match = re.search(r"GOL\.?\s*DARAH\s*[:.\-]?\s*(AB|A|B|O|-)", raw, flags=re.IGNORECASE)
    if gol_match:
        golongan_darah = normalize_blood_type(gol_match.group(1))

    alamat = find_labeled_value(raw, [
        r"ALAMAT",
        r"ALAMA",
    ])
    alamat = stop_at_next_label(alamat)
    alamat = clean_words(alamat, min_len=5)

    rt_rw = extract_rt_rw(raw)

    kel_desa = find_labeled_value(raw, [
        r"KEL\s*/?\s*DESA",
        r"KELURAHAN",
        r"DESA",
    ])
    kel_desa = clean_words(stop_at_next_label(kel_desa))

    kecamatan = find_labeled_value(raw, [
        r"KECAMATAN",
        r"MECAMATAN",
    ])
    kecamatan = clean_words(stop_at_next_label(kecamatan))

    agama_raw = find_labeled_value(raw, [
        r"AGAMA",
    ])
    agama = normalize_religion(agama_raw)

    status_raw = find_labeled_value(raw, [
        r"STATUS\s*PERKAWINAN",
        r"STATUS",
    ])
    status_perkawinan = normalize_marital(status_raw)

    pekerjaan = find_labeled_value(raw, [
        r"PEKERJAAN",
    ])
    pekerjaan = clean_words(stop_at_next_label(pekerjaan))

    kewarganegaraan_raw = find_labeled_value(raw, [
        r"KEWARGANEGARAAN",
        r"KEWARGA\s*NEGARAAN",
    ])
    kewarganegaraan = None
    source = f"{kewarganegaraan_raw or ''} {raw}".upper()
    if "WNI" in source:
        kewarganegaraan = "WNI"
    elif "WNA" in source:
        kewarganegaraan = "WNA"

    berlaku_raw = find_labeled_value(raw, [
        r"BERLAKU\s*HINGGA",
        r"BERLAKU",
    ])
    berlaku_hingga = normalize_valid_until(berlaku_raw)

    # Use all dates. First date is usually birth date, last date may be issue/signature date.
    all_dates = []
    for match in re.finditer(r"\b\d{1,2}[-/.]\s*\d{1,2}[-/.]\s*\d{4}\b", repair_digit_text(raw)):
        d = extract_date(match.group(0))
        if d:
            all_dates.append(d)

    if not tanggal_lahir and all_dates:
        tanggal_lahir = all_dates[0]

    tanggal_penerbitan = None
    if len(all_dates) >= 2:
        tanggal_penerbitan = all_dates[-1]

    fields = {
        "nik": nik,
        "nama": nama,
        "tempat_lahir": tempat_lahir,
        "tanggal_lahir": tanggal_lahir,
        "jenis_kelamin": jenis_kelamin,
        "golongan_darah": golongan_darah,
        "alamat": alamat,
        "rt_rw": rt_rw,
        "kel_desa": kel_desa,
        "kecamatan": kecamatan,
        "agama": agama,
        "status_perkawinan": status_perkawinan,
        "pekerjaan": pekerjaan,
        "tanggal_penerbitan": tanggal_penerbitan,
        "kewarganegaraan": kewarganegaraan,
        "berlaku_hingga": berlaku_hingga,
    }

    for key, value in fields.items():
        if isinstance(value, str):
            fields[key] = normalize_value(value)

    return fields


# ============================================================
# NPWP extraction
# ============================================================

def extract_npwp_fields(text: str) -> dict[str, Any]:
    raw = clean_text(text)
    lines = text_lines(raw)

    npwp15 = get_npwp15(raw)
    npwp16 = get_npwp16(raw) if "NPWP" in raw.upper() else None

    nama = find_labeled_value(raw, [r"NAMA\s*WAJIB\s*PAJAK", r"NAMA", r"WAJIB\s*PAJAK"])
    alamat = find_labeled_value(raw, [r"ALAMAT"])
    terdaftar_raw = find_labeled_value(raw, [r"TANGGAL\s*TERDAFTAR", r"TERDAFTAR"])
    kpp = find_labeled_value(raw, [r"KPP\s*PRATAMA", r"KPP"])

    if npwp15 and (not nama or not alamat):
        digits_npwp = re.sub(r"\D", "", npwp15)
        for i, line in enumerate(lines):
            if digits_npwp and digits_npwp in re.sub(r"\D", "", line):
                after = [normalize_value(x) for x in lines[i + 1:i + 7] if normalize_value(x)]
                filtered = [
                    x for x in after
                    if not re.search(r"NPWP|KPP|TERDAFTAR|PAJAK", x, flags=re.IGNORECASE)
                ]

                if filtered and not nama:
                    nama = filtered[0]

                if len(filtered) >= 2 and not alamat:
                    alamat = " ".join(filtered[1:4])

                break

    terdaftar = extract_date(terdaftar_raw) if terdaftar_raw else None
    if not terdaftar:
        terdaftar = extract_date(raw)

    return {
        "npwp": npwp15,
        "npwp15": npwp15,
        "npwp16": npwp16,
        "nama": clean_person_name(nama),
        "alamat": clean_words(alamat, min_len=8),
        "terdaftar": terdaftar,
        "kpp": clean_words(kpp, min_len=3),
    }


# ============================================================
# Scoring
# ============================================================

def get_max_score(document_type: str) -> int:
    if document_type == "KTP":
        return 14
    if document_type == "NPWP":
        return 6
    return 0


def get_score_percent(document_type: str, score: int) -> float:
    max_score = get_max_score(document_type)
    if max_score <= 0:
        return 0.0
    return round((score / max_score) * 100, 2)


def is_valid_ktp_field(field: str, value: Any) -> bool:
    if value is None or value == "":
        return False

    value = str(value).upper().strip()

    if field == "nik":
        return bool(re.fullmatch(r"\d{16}", value))

    if field == "nama":
        return bool(re.fullmatch(r"[A-Z\s.'-]{3,80}", value)) and not any(
            bad in value for bad in ["NIK", "ALAMAT", "RT", "RW", "KECAMATAN", "PROVINSI", "KABUPATEN"]
        )

    if field == "tempat_lahir":
        return bool(re.fullmatch(r"[A-Z\s.'-]{3,50}", value))

    if field == "tanggal_lahir":
        return is_valid_date(value)

    if field == "jenis_kelamin":
        return value in ["LAKI-LAKI", "PEREMPUAN"]

    if field == "alamat":
        if re.search(r"\d{1,3}\s*/\s*\d{1,3}", value):
            return False
        return len(value) >= 5 and not any(bad in value for bad in ["KECAMATAN", "AGAMA", "PEKERJAAN"])

    if field == "rt_rw":
        return bool(re.fullmatch(r"\d{3}/\d{3}", value))

    if field == "kel_desa":
        return len(value) >= 3 and not any(bad in value for bad in ["KECAMATAN", "AGAMA"])

    if field == "kecamatan":
        return len(value) >= 3 and not any(bad in value for bad in ["AGAMA", "PEKERJAAN", "BERLAKU"])

    if field == "agama":
        return value in ["ISLAM", "KRISTEN", "KATOLIK", "HINDU", "BUDDHA", "KONGHUCU"]

    if field == "status_perkawinan":
        return value in ["BELUM KAWIN", "KAWIN", "CERAI HIDUP", "CERAI MATI"]

    if field == "pekerjaan":
        return len(value) >= 3 and not any(bad in value for bad in ["WNI", "SEUMUR", "BERLAKU"])

    if field == "kewarganegaraan":
        return value in ["WNI", "WNA"]

    if field == "berlaku_hingga":
        return value == "SEUMUR HIDUP" or is_valid_date(value)

    return bool(value)


def is_valid_npwp_field(field: str, value: Any) -> bool:
    if value is None or value == "":
        return False

    value = str(value).upper().strip()

    if field == "npwp15":
        return len(re.sub(r"\D", "", value)) == 15

    if field == "npwp16":
        return len(re.sub(r"\D", "", value)) == 16

    if field == "nama":
        return len(value) >= 3 and "NPWP" not in value

    if field == "alamat":
        return len(value) >= 8 and "NPWP" not in value

    if field == "terdaftar":
        return is_valid_date(value)

    if field == "kpp":
        return len(value) >= 3

    return bool(value)


def calculate_score(document_type: str, fields: dict[str, Any]) -> int:
    if document_type == "KTP":
        important = [
            "nik",
            "nama",
            "tempat_lahir",
            "tanggal_lahir",
            "jenis_kelamin",
            "alamat",
            "rt_rw",
            "kel_desa",
            "kecamatan",
            "agama",
            "status_perkawinan",
            "pekerjaan",
            "kewarganegaraan",
            "berlaku_hingga",
        ]
        return sum(1 for field in important if is_valid_ktp_field(field, fields.get(field)))

    if document_type == "NPWP":
        important = ["npwp15", "npwp16", "nama", "alamat", "terdaftar", "kpp"]
        return sum(1 for field in important if is_valid_npwp_field(field, fields.get(field)))

    return 0


def needs_manual_review(document_type: str, fields: dict[str, Any], score: int) -> bool:
    if document_type == "KTP":
        return (
            not is_valid_ktp_field("nik", fields.get("nik"))
            or not is_valid_ktp_field("nama", fields.get("nama"))
            or not is_valid_ktp_field("tanggal_lahir", fields.get("tanggal_lahir"))
            or score < 9
        )

    if document_type == "NPWP":
        return (
            not is_valid_npwp_field("npwp15", fields.get("npwp15"))
            or not is_valid_npwp_field("nama", fields.get("nama"))
            or score < 4
        )

    return True


def review_reasons(document_type: str, fields: dict[str, Any], score: int) -> list[str]:
    reasons = []

    if document_type == "KTP":
        if not is_valid_ktp_field("nik", fields.get("nik")):
            reasons.append("NIK is missing or invalid")
        if not is_valid_ktp_field("nama", fields.get("nama")):
            reasons.append("Nama is missing or invalid")
        if not is_valid_ktp_field("tanggal_lahir", fields.get("tanggal_lahir")):
            reasons.append("Tanggal lahir is missing or invalid")
        if score < 9:
            reasons.append("KTP score is below acceptance threshold")

    elif document_type == "NPWP":
        if not is_valid_npwp_field("npwp15", fields.get("npwp15")):
            reasons.append("NPWP15 is missing or invalid")
        if not is_valid_npwp_field("nama", fields.get("nama")):
            reasons.append("Nama is missing or invalid")
        if score < 4:
            reasons.append("NPWP score is below acceptance threshold")
    else:
        reasons.append("Document type could not be detected")

    return reasons


def extraction_quality_score(text: str) -> int:
    doc_type = detect_document_type(text)

    if doc_type == "KTP":
        fields = extract_ktp_fields(text)
    elif doc_type == "NPWP":
        fields = extract_npwp_fields(text)
    else:
        fields = {}

    score = calculate_score(doc_type, fields)

    upper = text.upper()
    keyword_bonus = 0
    for keyword in ["NIK", "NAMA", "ALAMAT", "KECAMATAN", "AGAMA", "NPWP", "KPP", "TERDAFTAR"]:
        if keyword in upper:
            keyword_bonus += 1

    chars = re.sub(r"\s", "", text)
    alnum = re.sub(r"[^A-Za-z0-9]", "", chars)
    noise_penalty = 0
    if chars:
        noise_ratio = 1 - (len(alnum) / len(chars))
        if noise_ratio > 0.40:
            noise_penalty = 8

    return (score * 100) + keyword_bonus - noise_penalty


# ============================================================
# Image and OCR
# ============================================================

def file_to_images(file_path: str) -> list[tuple[str, np.ndarray]]:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()

    if ext == ".pdf":
        pages = convert_from_path(
            str(path),
            dpi=PDF_DPI,
            poppler_path=POPPLER_PATH,
        )

        images = []
        for idx, page in enumerate(pages, start=1):
            rgb = np.array(page)
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            images.append((f"PDF PAGE {idx}", bgr))

        return images

    if ext in [".jpg", ".jpeg", ".png"]:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Failed to read image file: {file_path}")
        return [("PAGE 1", image)]

    raise ValueError(f"Unsupported file extension: {ext}")


def to_tesseract_image(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def sharpen_image(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
    return cv2.addWeighted(gray, 1.6, blur, -0.6, 0)


def preprocess_variants(image: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """
    Safer variants for KTP/NPWP.
    Avoid aggressive adaptive threshold by default because it often converts
    KTP background texture into fake OCR characters.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants: list[tuple[str, np.ndarray]] = []

    variants.append(("gray", gray))

    up2 = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    variants.append(("upscale-2x", up2))
    variants.append(("upscale-2x-sharpen", sharpen_image(up2)))

    up3 = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    variants.append(("upscale-3x", up3))
    variants.append(("upscale-3x-sharpen", sharpen_image(up3)))

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    variants.append(("upscale-3x-clahe", clahe.apply(up3)))

    denoise = cv2.fastNlMeansDenoising(up3, None, 7, 7, 21)
    variants.append(("upscale-3x-denoise-sharpen", sharpen_image(denoise)))

    # Light Otsu only as last candidate.
    blur = cv2.GaussianBlur(up3, (3, 3), 0)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("upscale-3x-otsu", otsu))

    return variants


def tesseract_text(image: np.ndarray, config: str) -> str:
    return clean_text(
        pytesseract.image_to_string(
            to_tesseract_image(image),
            lang="ind+eng",
            config=config,
        )
    )


def tesseract_candidate(file_path: str, engine_name: str, use_variants: bool) -> dict[str, Any]:
    images = file_to_images(file_path)
    all_text = []

    configs = [
        "--oem 3 --psm 6",
        "--oem 3 --psm 11",
    ]

    for page_label, image in images:
        variants = preprocess_variants(image) if use_variants else [("original", image)]

        best_page_text = ""
        best_page_score = -10**9

        for variant_name, variant_image in variants:
            for config in configs:
                cleaned = tesseract_text(variant_image, config)
                current_score = extraction_quality_score(cleaned)

                if current_score > best_page_score:
                    best_page_score = current_score
                    best_page_text = cleaned

        all_text.append(f"--- {page_label} ---\n{best_page_text}")

    raw_text = clean_text("\n".join(all_text))
    document_type = detect_document_type(raw_text)

    if document_type == "KTP":
        fields = extract_ktp_fields(raw_text)
    elif document_type == "NPWP":
        fields = extract_npwp_fields(raw_text)
    else:
        fields = {}

    score = calculate_score(document_type, fields)

    return {
        "ocr_enabled": True,
        "ocr_status": "success",
        "ocr_engine": engine_name,
        "ocr_provider": "self-hosted-free",
        "document_type": document_type,
        "extracted_at": now_iso(),
        "fields": fields,
        "raw_text": raw_text,
        "score": score,
    }


def paddleocr_candidate(file_path: str) -> dict[str, Any]:
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:
        raise RuntimeError(f"PaddleOCR is not installed or failed to load: {exc}")

    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    images = file_to_images(file_path)

    all_lines = []
    confidences = []

    with tempfile.TemporaryDirectory() as temp_dir:
        for page_index, (page_label, image) in enumerate(images, start=1):
            temp_path = str(Path(temp_dir) / f"page_{page_index}.png")
            cv2.imwrite(temp_path, image)

            result = ocr.ocr(temp_path, cls=True)
            all_lines.append(f"--- {page_label} ---")

            for block in result or []:
                for item in block or []:
                    try:
                        text = item[1][0]
                        conf = float(item[1][1])
                    except Exception:
                        continue

                    all_lines.append(str(text))
                    confidences.append(conf)

    raw_text = clean_text("\n".join(all_lines))
    document_type = detect_document_type(raw_text)

    if document_type == "KTP":
        fields = extract_ktp_fields(raw_text)
    elif document_type == "NPWP":
        fields = extract_npwp_fields(raw_text)
    else:
        fields = {}

    score = calculate_score(document_type, fields)
    confidence_avg = round(sum(confidences) / len(confidences), 4) if confidences else None

    return {
        "ocr_enabled": True,
        "ocr_status": "success",
        "ocr_engine": "paddleocr-local-api",
        "ocr_provider": "self-hosted-free",
        "document_type": document_type,
        "confidence_avg": confidence_avg,
        "extracted_at": now_iso(),
        "fields": fields,
        "raw_text": raw_text,
        "score": score,
    }


# ============================================================
# Payload and routing
# ============================================================

def build_single_engine_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    document_type = candidate.get("document_type", "UNKNOWN")
    fields = candidate.get("fields") or {}

    score = calculate_score(document_type, fields)
    score_max = get_max_score(document_type)
    score_percent = get_score_percent(document_type, score)
    manual_review_required = needs_manual_review(document_type, fields, score)

    payload = {
        "ocr_enabled": True,
        "ocr_status": candidate.get("ocr_status", "success"),
        "ocr_engine": candidate.get("ocr_engine"),
        "ocr_provider": candidate.get("ocr_provider", "self-hosted-free"),
        "document_type": document_type,
        "extracted_at": candidate.get("extracted_at", now_iso()),
        "manual_review_required": manual_review_required,
        "review_reasons": review_reasons(document_type, fields, score) if manual_review_required else [],
        "score": score,
        "score_max": score_max,
        "score_percent": score_percent,
        "fields": fields,
        "raw_text": candidate.get("raw_text", ""),
    }

    if candidate.get("confidence_avg") is not None:
        payload["confidence_avg"] = candidate.get("confidence_avg")

    if candidate.get("error"):
        payload["error"] = candidate.get("error")

    return payload


def error_payload(engine_name: str, error: Exception) -> dict[str, Any]:
    return {
        "ocr_enabled": True,
        "ocr_status": "failed",
        "ocr_engine": engine_name,
        "ocr_provider": "self-hosted-free",
        "document_type": "UNKNOWN",
        "extracted_at": now_iso(),
        "manual_review_required": True,
        "review_reasons": [str(error)],
        "score": 0,
        "score_max": 0,
        "score_percent": 0.0,
        "fields": {},
        "raw_text": "",
        "error": str(error),
    }


def choose_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [c for c in candidates if c.get("ocr_status") == "success"]

    if not successful:
        return candidates[0] if candidates else error_payload("unknown", RuntimeError("No OCR candidate produced"))

    return max(
        successful,
        key=lambda c: (
            calculate_score(c.get("document_type", "UNKNOWN"), c.get("fields") or {}),
            extraction_quality_score(c.get("raw_text", "")),
        ),
    )


def run_ocr(file_path: str, library: str) -> dict[str, Any]:
    library = (library or "").lower().strip()

    try:
        # Order matters. "OpenCV Tesseract" contains "tesseract",
        # so OpenCV must be checked before Tesseract.
        if "hybrid" in library:
            candidates = []

            for engine_name, use_variants in [
                ("tesseract-local-cli", False),
                ("opencv-tesseract", True),
            ]:
                try:
                    candidates.append(tesseract_candidate(file_path, engine_name, use_variants))
                except Exception as exc:
                    candidates.append(error_payload(engine_name, exc))

            try:
                candidates.append(paddleocr_candidate(file_path))
            except Exception as exc:
                candidates.append(error_payload("paddleocr-local-api", exc))

            candidate = choose_best_candidate(candidates)
            payload = build_single_engine_payload(candidate)

            return {
                "document_type": payload.get("document_type", "UNKNOWN"),
                "payload": payload,
            }

        if "opencv" in library:
            candidate = tesseract_candidate(
                file_path=file_path,
                engine_name="opencv-tesseract",
                use_variants=True,
            )
            payload = build_single_engine_payload(candidate)

            return {
                "document_type": payload.get("document_type", "UNKNOWN"),
                "payload": payload,
            }

        if "paddle" in library:
            candidate = paddleocr_candidate(file_path)
            payload = build_single_engine_payload(candidate)

            return {
                "document_type": payload.get("document_type", "UNKNOWN"),
                "payload": payload,
            }

        if "tesseract" in library:
            candidate = tesseract_candidate(
                file_path=file_path,
                engine_name="tesseract-local-cli",
                use_variants=False,
            )
            payload = build_single_engine_payload(candidate)

            return {
                "document_type": payload.get("document_type", "UNKNOWN"),
                "payload": payload,
            }

        raise ValueError(f"Unsupported OCR library: {library}")

    except Exception as exc:
        payload = error_payload("ocr-engine", exc)
        return {
            "document_type": "UNKNOWN",
            "payload": payload,
        }
