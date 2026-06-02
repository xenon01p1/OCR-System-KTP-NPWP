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
PDF_DPI = int(os.getenv("OCR_PDF_DPI", "350"))
OCR_SPEED_MODE = os.getenv("OCR_SPEED_MODE", "balanced").lower().strip()

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

KTP_SCORE_FIELDS = [
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

KTP_FIELD_ORDER = [
    "nik",
    "nama",
    "agama",
    "rt_rw",
    "alamat",
    "kel_desa",
    "kecamatan",
    "pekerjaan",
    "tempat_lahir",
    "jenis_kelamin",
    "tanggal_lahir",
    "berlaku_hingga",
    "golongan_darah",
    "kewarganegaraan",
    "status_perkawinan",
    "tanggal_penerbitan",
]

NPWP_SCORE_FIELDS = [
    "kpp",
    "npwp15",
    "npwp16",
    "nama",
    "alamat",
    "kelurahan_kecamatan",
    "kabupaten_provinsi",
    "tanggal_terdaftar",
    "penerbit",
]

NPWP_FIELD_ORDER = [
    "kpp",
    "npwp",
    "npwp15",
    "npwp16",
    "nama",
    "alamat",
    "kelurahan_kecamatan",
    "kabupaten_provinsi",
    "tanggal_terdaftar",
    "penerbit",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).replace("\x0c", "")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_line(line: str) -> str:
    if not line:
        return ""
    line = str(line).strip()
    line = line.replace("|", "I")
    line = line.replace("=", ":").replace(";", ":").replace(">", ":")
    line = re.sub(r"[\t ]+", " ", line)
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
    return re.sub(r"[^A-Z]", "", text)


def repair_digit_text(value: str) -> str:
    table = str.maketrans({
        "O": "0", "o": "0", "Q": "0", "D": "0",
        "I": "1", "l": "1", "|": "1", "!": "1",
        "S": "5", "s": "5", "B": "8", "G": "6",
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
    day_i, month_i, year_i = int(day), int(month), int(year)
    if not (1 <= day_i <= 31 and 1 <= month_i <= 12 and 1900 <= year_i <= 2100):
        return None
    return f"{day_i:02d}-{month_i:02d}-{year_i}"


def is_valid_date(value: Any) -> bool:
    return extract_date(str(value)) is not None if value else False


def clean_words(value: str | None, min_len: int = 3) -> str | None:
    value = normalize_value(value)
    if not value:
        return None
    value = re.sub(r"[^A-Z0-9\s.'/\-&]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) >= min_len else None


def remove_embedded_labels(value: str | None) -> str | None:
    value = normalize_value(value)
    if not value:
        return None
    stop_patterns = [
        r"\bNIK\b", r"\bNAMA\b", r"\bNAME\b", r"\bTEMPAT\b", r"\bJENIS\b",
        r"\bGOL\.?\s*DARAH\b", r"\bALAMAT\b", r"\bRT\s*/?\s*RW\b",
        r"\bKEL\s*/?\s*DESA\b", r"\bKELURAHAN\b", r"\bKECAMATAN\b",
        r"\bAGAMA\b", r"\bSTATUS\b", r"\bPEKERJAAN\b", r"\bKEWARGANEGARAAN\b",
        r"\bBERLAKU\b", r"\bNPWP\b", r"\bNPWP\s*15\b", r"\bNPWP\s*16\b", r"\bWAJIB\s*PAJAK\b",
        r"\bKPP\b", r"\bTERDAFTAR\b", r"\bPENERBIT\b", r"\bKANTOR\b",
    ]
    cut = len(value)
    for pattern in stop_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match and match.start() > 0:
            cut = min(cut, match.start())
    return normalize_value(value[:cut])


def clean_person_name(value: str | None) -> str | None:
    value = remove_embedded_labels(value)
    if not value:
        return None
    value = re.sub(r"[^A-Z\s.'-]", " ", value)
    value = re.sub(r"\b(NIK|NAMA|NAME|ALAMAT|TEMPAT|TGL|LAHIR|PROVINSI|KABUPATEN|NPWP|NPWP15|NPWP16|PAJAK|WAJIB|WAJIBPAJAK|DIGIT)\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) >= 3 else None


def flatten_for_inline_extraction(text: str) -> str:
    flat = clean_text(text).replace("\n", " ")
    flat = normalize_line(flat)
    return re.sub(r"\s+", " ", flat).strip()


def find_labeled_value(text: str, label_patterns: list[str]) -> str | None:
    lines = text_lines(text)

    for line in lines:
        upper = normalize_line(line).upper()
        for label_pattern in label_patterns:
            pattern = rf"\b(?:{label_pattern})\b\s*[:.\-_/\\ ]*\s*(.+?)\s*$"
            match = re.search(pattern, upper, flags=re.IGNORECASE)
            if match:
                value = normalize_value(match.group(1))
                if value:
                    return value

    flat = flatten_for_inline_extraction(text).upper()
    terminators = [
        r"KANTOR\s+PELAYANAN\s+PAJAK", r"KPP\s+PRATAMA", r"KPP", r"NPWP\s*\(?\s*15",
        r"NPWP\s*15", r"NPWP\s*\(?\s*16", r"NPWP16", r"NAMA\s+WAJIB\s+PAJAK",
        r"NAMA", r"ALAMAT", r"KELURAHAN\s*/\s*KECAMATAN", r"KEL\s*/\s*KEC",
        r"KABUPATEN\s*&\s*PROVINSI", r"KABUPATEN\s+DAN\s+PROVINSI", r"TANGGAL\s+TERDAFTAR",
        r"TERDAFTAR", r"PENERBIT", r"DIREKTORAT\s+JENDERAL\s+PAJAK", r"WAJIB\s+PAJAK",
    ]
    stop = "|".join(terminators)

    for label_pattern in label_patterns:
        pattern = rf"(?:{label_pattern})\s*(?:\([^)]*\))?\s*[:.\-_/\\ ]+\s*(.*?)(?=\s+(?:{stop})\b|$)"
        match = re.search(pattern, flat, flags=re.IGNORECASE)
        if match:
            value = normalize_value(match.group(1))
            if value:
                return value

    return None


# ============================================================
# Document detection and numeric helpers
# ============================================================

def get_ktp_nik(text: str) -> str | None:
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
    match = re.search(r"\b\d{16}\b", text)
    return match.group(0) if match else None


def format_npwp15(digits: str | None) -> str | None:
    digits = re.sub(r"\D", "", digits or "")
    if len(digits) != 15:
        return None
    return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}.{digits[8]}-{digits[9:12]}.{digits[12:15]}"


def get_npwp15(text: str) -> str | None:
    repaired = repair_digit_text(text)
    patterns = [
        r"NPWP\s*(?:\(?\s*15\s*(?:DIGIT)?\s*\)?)?[^0-9A-Za-z]{0,20}([0-9OIl|! .\-]{15,35})",
        r"\b([0-9OIl|!]{2}[.\- ]?[0-9OIl|!]{3}[.\- ]?[0-9OIl|!]{3}[.\- ]?[0-9OIl|!]{1}[.\- ]?[0-9OIl|!]{3}[.\- ]?[0-9OIl|!]{3})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, repaired, flags=re.IGNORECASE)
        if not match:
            continue
        digits = re.sub(r"\D", "", repair_digit_text(match.group(1)))
        if len(digits) >= 15:
            return digits[:15]
    return None


def get_npwp16(text: str) -> str | None:
    repaired = repair_digit_text(text)
    patterns = [
        r"NPWP\s*16\s*(?:\([^)]*\))?[^0-9A-Za-z]{0,20}([0-9OIl|! ]{16,30})",
        r"NPWP16\s*(?:\([^)]*\))?[^0-9A-Za-z]{0,20}([0-9OIl|! ]{16,30})",
        r"\bNIK\b[^0-9A-Za-z]{0,20}([0-9OIl|! ]{16,30})",
        r"(?:16\s*DIGIT\s*.*?|NIK\s*.*?)\b([0-9OIl|! ]{16,25})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, repaired, flags=re.IGNORECASE)
        if not match:
            continue
        digits = re.sub(r"\D", "", repair_digit_text(match.group(1)))
        if len(digits) >= 16:
            return digits[:16]
            
    if "NPWP" in repaired.upper() or "PAJAK" in repaired.upper():
        cleaned_nums = re.findall(r"\b\d{16}\b", re.sub(r"[^\d\s]", " ", repaired))
        if cleaned_nums:
            return cleaned_nums[0]
            
    return None


def detect_document_type(text: str) -> str:
    upper = text.upper()
    ktp_score = 0
    npwp_score = 0

    npwp15 = get_npwp15(text)
    npwp16 = get_npwp16(text)
    ktp_nik = get_ktp_nik(text)

    if npwp15:
        npwp_score += 7
    if npwp16 and ("NPWP" in upper or "PAJAK" in upper or "KPP" in upper):
        npwp_score += 3
    if ktp_nik and not npwp15:
        ktp_score += 5

    for keyword in ["PROVINSI", "KABUPATEN", "KOTA", "KARTU TANDA PENDUDUK", "NIK", "KECAMATAN", "BERLAKU"]:
        if keyword in upper:
            ktp_score += 1

    for keyword in ["NPWP", "NPWP16", "KPP", "PAJAK", "TERDAFTAR", "WAJIB PAJAK", "DIREKTORAT JENDERAL PAJAK"]:
        if keyword in upper:
            npwp_score += 1

    for line in text_lines(text):
        key = alpha_key(line)
        if fuzz.partial_ratio("PROVINSI", key) >= 82:
            ktp_score += 1
        if fuzz.partial_ratio("KABUPATEN", key) >= 82:
            ktp_score += 1
        if fuzz.partial_ratio("KECAMATAN", key) >= 82:
            ktp_score += 1
        if fuzz.partial_ratio("NPWP", key) >= 82:
            npwp_score += 2
        if fuzz.partial_ratio("WAJIBPAJAK", key) >= 82:
            npwp_score += 2

    if npwp_score >= 3 and npwp_score >= ktp_score:
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
    repaired = repair_digit_text(value)
    match = re.search(r"\d{1,2}[-/.]\s*\d{1,2}[-/.]\s*\d{4}", repaired)
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
    for item in ["ISLAM", "KRISTEN", "KATOLIK", "HINDU", "BUDDHA", "KONGHUCU"]:
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
    nama = clean_person_name(find_labeled_value(raw, [r"NAMA", r"NAME"]))

    ttl = find_labeled_value(raw, [
        r"TEMPAT\s*/?\s*TGL\.?\s*LAHIR", r"TEMPAT\s*TGL\.?\s*LAHIR",
        r"TEMPATI?\s*TG[LI!1]?\s*LAHIR", r"TEMPAT.*LAHIR",
    ])
    tempat_lahir, tanggal_lahir = split_birth_place_date(ttl)

    jenis_kelamin = normalize_gender(find_labeled_value(raw, [r"JENIS\s*KELAMIN"]))

    golongan_darah = None
    gol_match = re.search(r"GOL\.?\s*DARAH\s*[:.\-]?\s*(AB|A|B|O|-)", raw, flags=re.IGNORECASE)
    if gol_match:
        golongan_darah = normalize_blood_type(gol_match.group(1))

    alamat = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"ALAMAT", r"ALAMA"])), min_len=5)
    rt_rw = extract_rt_rw(raw)
    kel_desa = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"KEL\s*/?\s*DESA", r"KELURAHAN", r"DESA"])))
    kecamatan = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"KECAMATAN", r"MECAMATAN"])))
    agama = normalize_religion(find_labeled_value(raw, [r"AGAMA"]))
    status_perkawinan = normalize_marital(find_labeled_value(raw, [r"STATUS\s*PERKAWINAN", r"STATUS"]))
    pekerjaan = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"PEKERJAAN"])))

    kewarganegaraan_raw = find_labeled_value(raw, [r"KEWARGANEGARAAN", r"KEWARGA\s*NEGARAAN"])
    source = f"{kewarganegaraan_raw or ''} {raw}".upper()
    kewarganegaraan = "WNI" if "WNI" in source else ("WNA" if "WNA" in source else None)

    berlaku_hingga = normalize_valid_until(find_labeled_value(raw, [r"BERLAKU\s*HINGGA", r"BERLAKU"]))

    all_dates = []
    for match in re.finditer(r"\b\d{1,2}[-/.]\s*\d{1,2}[-/.]\s*\d{4}\b", repair_digit_text(raw)):
        d = extract_date(match.group(0))
        if d:
            all_dates.append(d)

    if not tanggal_lahir and all_dates:
        tanggal_lahir = all_dates[0]

    tanggal_penerbitan = all_dates[-1] if len(all_dates) >= 2 else None

    fields = {
        "nik": nik,
        "nama": nama,
        "agama": agama,
        "rt_rw": rt_rw,
        "alamat": alamat,
        "kel_desa": kel_desa,
        "kecamatan": kecamatan,
        "pekerjaan": pekerjaan,
        "tempat_lahir": tempat_lahir,
        "jenis_kelamin": jenis_kelamin,
        "tanggal_lahir": tanggal_lahir,
        "berlaku_hingga": berlaku_hingga,
        "golongan_darah": golongan_darah,
        "kewarganegaraan": kewarganegaraan,
        "status_perkawinan": status_perkawinan,
        "tanggal_penerbitan": tanggal_penerbitan,
    }
    return order_fields({k: normalize_value(v) if isinstance(v, str) else v for k, v in fields.items()}, KTP_FIELD_ORDER)


# ============================================================
# NPWP extraction
# ============================================================

def normalize_penerbit(value: str | None, raw: str) -> str | None:
    combined = f"{value or ''} {raw}".upper()
    if "DJP" in combined or "DIREKTORAT JENDERAL PAJAK" in combined:
        return "DJP"
    return clean_words(value, min_len=2)


def extract_npwp_fields(text: str) -> dict[str, Any]:
    raw = clean_text(text)

    npwp15 = get_npwp15(raw)
    npwp16 = get_npwp16(raw)

    kpp = find_labeled_value(raw, [r"KANTOR\s+PELAYANAN\s+PAJAK", r"KPP\s+PRATAMA", r"KPP"])
    if kpp:
        kpp = clean_words(kpp, min_len=3)
        if kpp and not kpp.startswith("KPP") and "PRATAMA" in kpp:
            kpp = f"KPP {kpp}"

    nama = clean_person_name(find_labeled_value(raw, [r"NAMA\s+WAJIB\s+PAJAK", r"WAJIB\s+PAJAK", r"NAMA"]))
    alamat = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"ALAMAT"])), min_len=6)
    
    kel_kec = find_labeled_value(raw, [r"KELURAHAN\s*/\s*KECAMATAN", r"KEL\s*/\s*KEC", r"KELURAHAN", r"KECAMATAN"])
    kel_kec = clean_words(remove_embedded_labels(kel_kec), min_len=3)
    
    kab_prov = find_labeled_value(raw, [r"KABUPATEN\s*&\s*PROVINSI", r"KABUPATEN\s+DAN\s+PROVINSI", r"KAB\.?\s*&\s*PROV", r"KABUPATEN", r"PROVINSI"])
    kab_prov = clean_words(remove_embedded_labels(kab_prov), min_len=3)
    
    terdaftar_raw = find_labeled_value(raw, [r"TANGGAL\s+TERDAFTAR", r"TERDAFTAR"])
    tanggal_terdaftar = extract_date(terdaftar_raw) or extract_date(raw)
    penerbit = normalize_penerbit(find_labeled_value(raw, [r"PENERBIT", r"DIREKTORAT\s+JENDERAL\s+PAJAK", r"DJP"]), raw)

    if npwp15 and (not nama or not alamat):
        lines = [normalize_value(x) for x in text_lines(raw)]
        lines = [x for x in lines if x]
        digits_npwp = re.sub(r"\D", "", npwp15)
        for i, line in enumerate(lines):
            if digits_npwp in re.sub(r"\D", "", line):
                after = [x for x in lines[i + 1:i + 8] if not re.search(r"NPWP|KPP|TERDAFTAR|PAJAK", x, flags=re.IGNORECASE)]
                if after and not nama:
                    nama = clean_person_name(after[0])
                if len(after) >= 2 and not alamat:
                    alamat = clean_words(after[1], min_len=6)
                break

    fields = {
        "kpp": kpp,
        "npwp": format_npwp15(npwp15),
        "npwp15": npwp15,
        "npwp16": npwp16,
        "nama": nama,
        "alamat": alamat,
        "kelurahan_kecamatan": kel_kec,
        "kabupaten_provinsi": kab_prov,
        "tanggal_terdaftar": tanggal_terdaftar,
        "penerbit": penerbit,
    }

    for key in ["kpp", "nama", "alamat", "kelurahan_kecamatan", "kabupaten_provinsi", "penerbit"]:
        if isinstance(fields.get(key), str):
            fields[key] = remove_embedded_labels(fields[key]) or fields[key]

    return order_fields({k: normalize_value(v) if isinstance(v, str) else v for k, v in fields.items()}, NPWP_FIELD_ORDER)


# ============================================================
# Scoring and payload validation logic
# ============================================================

def order_fields(fields: dict[str, Any], order: list[str]) -> dict[str, Any]:
    return {key: fields.get(key) for key in order}


def get_max_score(document_type: str) -> int:
    if document_type == "KTP":
        return len(KTP_SCORE_FIELDS)
    if document_type == "NPWP":
        return len(NPWP_SCORE_FIELDS)
    return 0


def get_score_percent(document_type: str, score: int) -> float:
    max_score = get_max_score(document_type)
    return round((score / max_score) * 100, 2) if max_score > 0 else 0.0


def is_valid_ktp_field(field: str, value: Any) -> bool:
    if value is None or value == "":
        return False
    value = str(value).upper().strip()

    if field == "nik":
        return bool(re.fullmatch(r"\d{16}", value))
    if field == "nama":
        return bool(re.fullmatch(r"[A-Z\s.'-]{3,80}", value)) and not any(bad in value for bad in ["NIK", "ALAMAT", "RT", "RW", "KECAMATAN", "PROVINSI", "KABUPATEN"])
    if field == "tempat_lahir":
        return bool(re.fullmatch(r"[A-Z\s.'-]{3,50}", value))
    if field == "tanggal_lahir":
        return is_valid_date(value)
    if field == "jenis_kelamin":
        return value in ["LAKI-LAKI", "PEREMPUAN"]
    if field == "alamat":
        return len(value) >= 5 and not re.search(r"\d{1,3}\s*/\s*\d{1,3}", value) and not any(bad in value for bad in ["KECAMATAN", "AGAMA", "PEKERJAAN"])
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
        return len(value) >= 3 and not any(bad in value for bad in ["NPWP", "PAJAK", "ALAMAT"])
    if field == "alamat":
        return len(value) >= 6 and "NPWP" not in value
    if field == "kelurahan_kecamatan":
        return len(value) >= 3 and "NPWP" not in value
    if field == "kabupaten_provinsi":
        return len(value) >= 3 and "NPWP" not in value
    if field == "tanggal_terdaftar":
        return is_valid_date(value)
    if field == "kpp":
        return len(value) >= 3 and ("KPP" in value or "PRATAMA" in value)
    if field == "penerbit":
        return len(value) >= 2
    return bool(value)


def calculate_score(document_type: str, fields: dict[str, Any]) -> int:
    if document_type == "KTP":
        return sum(1 for field in KTP_SCORE_FIELDS if is_valid_ktp_field(field, fields.get(field)))
    if document_type == "NPWP":
        return sum(1 for field in NPWP_SCORE_FIELDS if is_valid_npwp_field(field, fields.get(field)))
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
            or score < 6
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
        if score < 6:
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
    keyword_bonus = sum(1 for keyword in ["NIK", "NAMA", "ALAMAT", "KECAMATAN", "AGAMA", "NPWP", "KPP", "TERDAFTAR", "WAJIB PAJAK"] if keyword in upper)
    chars = re.sub(r"\s", "", text)
    alnum = re.sub(r"[^A-Za-z0-9]", "", chars)
    noise_penalty = 0
    if chars:
        noise_ratio = 1 - (len(alnum) / len(chars))
        if noise_ratio > 0.45:
            noise_penalty = 8
    return (score * 100) + keyword_bonus - noise_penalty


def build_single_engine_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    document_type = candidate.get("document_type", "UNKNOWN")
    fields = candidate.get("fields") or {}

    if document_type == "KTP":
        fields = order_fields(fields, KTP_FIELD_ORDER)
    elif document_type == "NPWP":
        fields = order_fields(fields, NPWP_FIELD_ORDER)

    score = calculate_score(document_type, fields)
    score_max = get_max_score(document_type)
    manual_review_required = needs_manual_review(document_type, fields, score)

    payload = {
        "score": score,
        "fields": fields,
        "raw_text": candidate.get("raw_text", ""),
        "score_max": score_max,
        "ocr_engine": candidate.get("ocr_engine"),
        "ocr_status": candidate.get("ocr_status", "success"),
        "ocr_enabled": True,
        "extracted_at": candidate.get("extracted_at", now_iso()),
        "ocr_provider": candidate.get("ocr_provider", "self-hosted-free"),
        "document_type": document_type,
        "score_percent": get_score_percent(document_type, score),
        "review_reasons": review_reasons(document_type, fields, score) if manual_review_required else [],
        "manual_review_required": manual_review_required,
    }

    if candidate.get("confidence_avg") is not None:
        payload["confidence_avg"] = candidate.get("confidence_avg")
    if candidate.get("error"):
        payload["error"] = candidate.get("error")
    return payload


def error_payload(engine_name: str, error: Exception) -> dict[str, Any]:
    return {
        "score": 0,
        "fields": {},
        "raw_text": "",
        "score_max": 0,
        "ocr_engine": engine_name,
        "ocr_status": "failed",
        "ocr_enabled": True,
        "extracted_at": now_iso(),
        "ocr_provider": "self-hosted-free",
        "document_type": "UNKNOWN",
        "score_percent": 0.0,
        "review_reasons": [str(error)],
        "manual_review_required": True,
        "error": str(error),
    }


# ============================================================
# Core File Readers & Engine Parsers
# ============================================================

def file_to_images(file_path: str) -> list[tuple[str, np.ndarray]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    if ext == ".pdf":
        pages = convert_from_path(str(path), dpi=PDF_DPI, poppler_path=POPPLER_PATH)
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
    return cv2.addWeighted(gray, 1.7, blur, -0.7, 0)


def preprocess_variants(image: np.ndarray) -> list[tuple[str, np.ndarray]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    if OCR_SPEED_MODE == "fast":
        up2 = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        return [
            ("gray", gray),
            ("upscale-2x", up2),
            ("upscale-2x-sharpen", sharpen_image(up2)),
        ]

    up2 = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    up3 = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    return [
        ("gray", gray),
        ("upscale-2x", up2),
        ("upscale-2x-sharpen", sharpen_image(up2)),
        ("upscale-3x-sharpen", sharpen_image(up3)),
        ("upscale-3x-clahe", clahe.apply(up3)),
    ]


def tesseract_text(image: np.ndarray, config: str) -> str:
    return clean_text(pytesseract.image_to_string(to_tesseract_image(image), lang="ind+eng", config=config))


def tesseract_candidate(file_path: str, engine_name: str, use_variants: bool) -> dict[str, Any]:
    images = file_to_images(file_path)
    all_text = []
    configs = ["--oem 3 --psm 6"] if OCR_SPEED_MODE == "fast" else ["--oem 3 --psm 6", "--oem 3 --psm 11"]

    for page_label, image in images:
        variants = preprocess_variants(image) if use_variants else [("original", image)]
        best_page_text = ""
        best_page_score = -10**9

        for _variant_name, variant_image in variants:
            for config in configs:
                cleaned = tesseract_text(variant_image, config)
                current_score = extraction_quality_score(cleaned)

                if current_score > best_page_score:
                    best_page_score = current_score
                    best_page_text = cleaned

                doc_type = detect_document_type(cleaned)
                if doc_type in ["KTP", "NPWP"]:
                    fields = extract_ktp_fields(cleaned) if doc_type == "KTP" else extract_npwp_fields(cleaned)
                    score = calculate_score(doc_type, fields)
                    if score >= get_max_score(doc_type):
                        best_page_text = cleaned
                        break
            else:
                continue
            break

        all_text.append(f"--- {page_label} ---\n{best_page_text}")

    raw_text = clean_text("\n".join(all_text))
    document_type = detect_document_type(raw_text)
    fields = extract_ktp_fields(raw_text) if document_type == "KTP" else (extract_npwp_fields(raw_text) if document_type == "NPWP" else {})

    return {
        "ocr_enabled": True,
        "ocr_status": "success",
        "ocr_engine": engine_name,
        "ocr_provider": "self-hosted-free",
        "document_type": document_type,
        "extracted_at": now_iso(),
        "fields": fields,
        "raw_text": raw_text,
        "score": calculate_score(document_type, fields),
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
    fields = extract_ktp_fields(raw_text) if document_type == "KTP" else (extract_npwp_fields(raw_text) if document_type == "NPWP" else {})

    return {
        "ocr_enabled": True,
        "ocr_status": "success",
        "ocr_engine": "paddleocr-local-api",
        "ocr_provider": "self-hosted-free",
        "document_type": document_type,
        "confidence_avg": round(sum(confidences) / len(confidences), 4) if confidences else None,
        "extracted_at": now_iso(),
        "fields": fields,
        "raw_text": raw_text,
        "score": calculate_score(document_type, fields),
    }


def easyocr_candidate(file_path: str) -> dict[str, Any]:
    try:
        import easyocr
    except Exception as exc:
        raise RuntimeError(f"EasyOCR is not installed or failed to load: {exc}")

    # Set gpu=True here if your machine has an active CUDA setup
    reader = easyocr.Reader(["id", "en"], gpu=False, verbose=False)
    images = file_to_images(file_path)
    all_lines = []

    for page_label, image in images:
        all_lines.append(f"--- {page_label} ---")
        
        # Read text along with positional data bounding boxes
        results = reader.readtext(image, detail=1)
        
        # Sort snippets structurally by top coordinates, then left coordinates
        results.sort(key=lambda x: (x[0][0][1], x[0][0][0]))
        
        for bbox, text, confidence in results:
            if confidence >= 0.20:  # Low confidence cutoff helps salvage blurred texts
                all_lines.append(str(text))

    raw_text = clean_text("\n".join(all_lines))
    document_type = detect_document_type(raw_text)
    fields = extract_ktp_fields(raw_text) if document_type == "KTP" else (extract_npwp_fields(raw_text) if document_type == "NPWP" else {})

    return {
        "ocr_enabled": True,
        "ocr_status": "success",
        "ocr_engine": "easyocr-local-api",
        "ocr_provider": "self-hosted-free",
        "document_type": document_type,
        "extracted_at": now_iso(),
        "fields": fields,
        "raw_text": raw_text,
        "score": calculate_score(document_type, fields),
    }


def choose_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [c for c in candidates if c.get("ocr_status") == "success"]
    if not successful:
        return candidates[0] if candidates else error_payload("unknown", RuntimeError("No OCR candidate produced"))
    return max(successful, key=lambda c: (calculate_score(c.get("document_type", "UNKNOWN"), c.get("fields") or {}), extraction_quality_score(c.get("raw_text", ""))))


def run_ocr(file_path: str, library: str) -> dict[str, Any]:
    library = (library or "").lower().strip()

    try:
        if "hybrid" in library:
            candidates = []
            for engine_name, use_variants in [("tesseract-local-cli", False), ("opencv-tesseract", True)]:
                try:
                    candidates.append(tesseract_candidate(file_path, engine_name, use_variants))
                except Exception as exc:
                    candidates.append(error_payload(engine_name, exc))
            for loader_fn, name in [(paddleocr_candidate, "paddleocr-local-api"), (easyocr_candidate, "easyocr-local-api")]:
                try:
                    candidates.append(loader_fn(file_path))
                except Exception as exc:
                    candidates.append(error_payload(name, exc))
                    
            payload = build_single_engine_payload(choose_best_candidate(candidates))
            return {"document_type": payload.get("document_type", "UNKNOWN"), "payload": payload}

        if "easy" in library:
            payload = build_single_engine_payload(easyocr_candidate(file_path))
            return {"document_type": payload.get("document_type", "UNKNOWN"), "payload": payload}

        if "opencv" in library:
            payload = build_single_engine_payload(tesseract_candidate(file_path, "opencv-tesseract", True))
            return {"document_type": payload.get("document_type", "UNKNOWN"), "payload": payload}

        if "paddle" in library:
            payload = build_single_engine_payload(paddleocr_candidate(file_path))
            return {"document_type": payload.get("document_type", "UNKNOWN"), "payload": payload}

        if "tesseract" in library:
            payload = build_single_engine_payload(tesseract_candidate(file_path, "tesseract-local-cli", False))
            return {"document_type": payload.get("document_type", "UNKNOWN"), "payload": payload}

        raise ValueError(f"Unsupported OCR library: {library}")

    except Exception as exc:
        payload = error_payload("ocr-engine", exc)
        return {"document_type": "UNKNOWN", "payload": payload}