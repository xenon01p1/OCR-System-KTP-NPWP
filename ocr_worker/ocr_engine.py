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
    value = re.sub(r"\s+", " ", value).strip(" &:-_/\\.,")
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
                    fields = extract_ktp_fields(cleaned, engine_name) if doc_type == "KTP" else extract_npwp_fields(cleaned, engine_name)
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
    fields = extract_ktp_fields(raw_text, engine_name) if document_type == "KTP" else (extract_npwp_fields(raw_text, engine_name) if document_type == "NPWP" else {})

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
    fields = extract_ktp_fields(raw_text, "PaddleOCR") if document_type == "KTP" else (extract_npwp_fields(raw_text, "PaddleOCR") if document_type == "NPWP" else {})

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
    fields = extract_ktp_fields(raw_text, "EasyOCR") if document_type == "KTP" else (extract_npwp_fields(raw_text, "EasyOCR") if document_type == "NPWP" else {})

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

# ============================================================
# Engine-aware raw OCR classification/extraction layer
# Implements:
# - Tesseract/OpenCV Tesseract: label/value line extraction first.
# - EasyOCR/PaddleOCR: semantic and proximity scanning fallback.
# ============================================================

SEMANTIC_ENGINE_NAMES = ("easyocr", "paddleocr", "paddle")


def is_semantic_engine(engine_name: str | None) -> bool:
    name = (engine_name or "").lower()
    return any(item in name for item in SEMANTIC_ENGINE_NAMES)


def is_line_engine(engine_name: str | None) -> bool:
    name = (engine_name or "").lower()
    return ("tesseract" in name or "opencv" in name) and not is_semantic_engine(name)


def strip_common_labels(value: str | None) -> str | None:
    value = normalize_value(value)
    if not value:
        return None
    patterns = [
        r"\bPROVINSI\b", r"\bKABUPATEN\b", r"\bKOTA\b", r"\bKARTU\s+TANDA\s+PENDUDUK\b",
        r"\bNIK\b", r"\bNAMA\b", r"\bTEMPAT\b", r"\bTGL\b", r"\bLAHIR\b",
        r"\bJENIS\s+KELAMIN\b", r"\bGOL\.?\s*DARAH\b", r"\bALAMAT\b",
        r"\bRT\s*/?\s*RW\b", r"\bKEL\s*/?\s*DESA\b", r"\bKELURAHAN\b",
        r"\bKECAMATAN\b", r"\bAGAMA\b", r"\bSTATUS\s+PERKAWINAN\b",
        r"\bPEKERJAAN\b", r"\bKEWARGANEGARAAN\b", r"\bBERLAKU\s+HINGGA\b",
        r"\bNPWP\b", r"\bWAJIB\s+PAJAK\b", r"\bKPP\b", r"\bPRATAMA\b",
        r"\bALAMAT\b", r"\bTERDAFTAR\b", r"\bPENERBIT\b",
        r"\bDIREKTORAT\s+JENDERAL\s+PAJAK\b",
    ]
    for pattern in patterns:
        value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip(" :-_/\\.,")
    return value or None


def line_matches_label(line: str, labels: list[str], threshold: int = 82) -> bool:
    key = alpha_key(line)
    if not key:
        return False

    visible = normalize_value(line) or ""
    for label in labels:
        label_key = alpha_key(label)
        if not label_key:
            continue

        # Short labels such as NAMA, KPP, and ALAMAT are easy to false-match
        # inside unrelated words like PRATAMA. Require an actual token/subsequence.
        if len(label_key) <= 5:
            token_pattern = r"\b" + re.escape(label.upper()) + r"\b"
            if re.search(token_pattern, visible, flags=re.IGNORECASE) or label_key in key:
                return True
            continue

        if label_key in key or fuzz.partial_ratio(label_key, key) >= threshold:
            return True

    return False


def is_bad_free_text_candidate(value: str | None) -> bool:
    value = normalize_value(value)
    if not value:
        return True
    if len(value) < 3:
        return True
    if re.fullmatch(r"[\d\s./\-:]+", value):
        return True
    blocked = [
        "PROVINSI", "KABUPATEN", "KOTA", "KARTU TANDA PENDUDUK",
        "NIK", "NPWP", "PAJAK", "DIREKTORAT", "DJP", "KPP",
        "AGAMA", "STATUS", "BERLAKU", "KEWARGANEGARAAN",
        "JENIS KELAMIN", "GOL", "TANGGAL TERDAFTAR",
        "ISLAM", "KRISTEN", "KATOLIK", "HINDU", "BUDDHA", "KONGHUCU",
        "KAWIN", "BELUM KAWIN", "CERAI", "WNI", "WNA", "SEUMUR HIDUP",
        "LAKI-LAKI", "PEREMPUAN",
    ]
    return any(word in value for word in blocked)


def score_candidate_text(value: str | None, prefer_person: bool = False) -> int:
    value = normalize_value(value)
    if not value:
        return -999
    alpha_count = len(re.findall(r"[A-Z]", value))
    digit_count = len(re.findall(r"\d", value))
    score = alpha_count - digit_count
    if prefer_person and re.fullmatch(r"[A-Z\s.'-]{3,80}", value):
        score += 10
    if is_bad_free_text_candidate(value):
        score -= 50
    return score


def nearby_value(
    raw: str,
    labels: list[str],
    *,
    cleaner=None,
    min_len: int = 3,
    prefer_person: bool = False,
    window: int = 2,
) -> str | None:
    lines = text_lines(raw)
    if not lines:
        return None

    candidates: list[tuple[int, str]] = []

    for i, line in enumerate(lines):
        if not line_matches_label(line, labels):
            continue

        # Same-line remainder, useful when OCR still keeps "Label Value".
        for label in labels:
            label_key = alpha_key(label)
            current_key = alpha_key(line)
            if label_key and label_key in current_key:
                # Try regex against the visible label string first.
                inline = re.sub(re.escape(label), " ", line, flags=re.IGNORECASE)
                inline = strip_common_labels(inline)
                if inline:
                    candidates.append((score_candidate_text(inline, prefer_person) + 40, inline))

        # Semantic engines often put the value above/below the label.
        for offset in [-2, -1, 1, 2]:
            j = i + offset
            if j < 0 or j >= len(lines):
                continue
            candidate = strip_common_labels(lines[j])
            if not candidate or len(candidate) < min_len:
                continue
            proximity_bonus = {1: 20, 2: 10, -1: 4, -2: 1}.get(offset, 0)
            candidates.append((score_candidate_text(candidate, prefer_person) + proximity_bonus, candidate))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    best = candidates[0][1]
    return cleaner(best) if cleaner else clean_words(best, min_len=min_len)


def semantic_fixed_value(raw: str, valid_values: list[str], threshold: int = 82) -> str | None:
    upper = normalize_value(raw) or ""
    key = alpha_key(upper)
    for item in valid_values:
        item_key = alpha_key(item)
        if item_key in key:
            return item
    for line in text_lines(raw):
        line_key = alpha_key(line)
        for item in valid_values:
            if fuzz.partial_ratio(alpha_key(item), line_key) >= threshold:
                return item
    return None


def semantic_ttl(raw: str) -> tuple[str | None, str | None]:
    # Prefer a line that contains both a place-like token and a date.
    for line in text_lines(raw):
        date = extract_date(line)
        if not date:
            continue
        tempat, tanggal = split_birth_place_date(line)
        if tempat and not is_bad_free_text_candidate(tempat):
            return tempat, tanggal

    ttl_near = nearby_value(
        raw,
        ["TEMPAT TGL LAHIR", "TEMPAT LAHIR", "TANGGAL LAHIR", "LAHIR"],
        cleaner=clean_words,
        min_len=3,
        window=2,
    )
    tempat, tanggal = split_birth_place_date(ttl_near)
    if tanggal:
        return tempat, tanggal

    dates = [extract_date(m.group(0)) for m in re.finditer(r"\b\d{1,2}[-/.]\s*\d{1,2}[-/.]\s*\d{4}\b", repair_digit_text(raw))]
    dates = [d for d in dates if d]
    return tempat, dates[0] if dates else None


def semantic_kpp(raw: str) -> str | None:
    lines = text_lines(raw)
    for i, line in enumerate(lines):
        upper = normalize_value(line) or ""
        if "KPP" in upper or "PRATAMA" in upper or line_matches_label(upper, ["KANTOR PELAYANAN PAJAK", "KPP PRATAMA", "KPP"]):
            merged = upper
            for j in [i + 1, i - 1]:
                if 0 <= j < len(lines):
                    adj = normalize_value(lines[j]) or ""
                    if "PRATAMA" in adj and adj not in merged:
                        merged = f"{merged} {adj}"
            merged = re.sub(r"\bKANTOR\s+PELAYANAN\s+PAJAK\b", "KPP", merged)
            merged = re.sub(r"\s+", " ", merged).strip()
            if "KPP" not in merged and "PRATAMA" in merged:
                merged = f"KPP {merged}"
            return clean_words(merged, min_len=3)
    return nearby_value(raw, ["KANTOR PELAYANAN PAJAK", "KPP PRATAMA", "KPP"], cleaner=clean_words, min_len=3)


def extract_ktp_fields(text: str, engine_name: str | None = None) -> dict[str, Any]:
    raw = clean_text(text)
    semantic = is_semantic_engine(engine_name)

    nik = get_ktp_nik(raw)
    rt_rw = extract_rt_rw(raw)

    if semantic:
        nama = nearby_value(raw, ["NAMA", "NAME"], cleaner=clean_person_name, min_len=3, prefer_person=True)
        tempat_lahir, tanggal_lahir = semantic_ttl(raw)

        jenis_kelamin = (
            semantic_fixed_value(raw, ["LAKI-LAKI", "PEREMPUAN"], threshold=76)
            or normalize_gender(nearby_value(raw, ["JENIS KELAMIN"], cleaner=clean_words, min_len=3))
            or normalize_gender(raw)
        )
        agama = (
            semantic_fixed_value(raw, ["ISLAM", "KRISTEN", "KATOLIK", "HINDU", "BUDDHA", "KONGHUCU"])
            or normalize_religion(nearby_value(raw, ["AGAMA"], cleaner=clean_words, min_len=3))
        )
        status_perkawinan = (
            semantic_fixed_value(raw, ["BELUM KAWIN", "KAWIN", "CERAI HIDUP", "CERAI MATI"], threshold=80)
            or normalize_marital(nearby_value(raw, ["STATUS PERKAWINAN", "STATUS"], cleaner=clean_words, min_len=3))
        )
        alamat = nearby_value(raw, ["ALAMAT"], cleaner=lambda v: clean_words(remove_embedded_labels(v), min_len=5), min_len=5)
        kel_desa = nearby_value(raw, ["KEL DESA", "KEL/DESA", "KELURAHAN", "DESA"], cleaner=lambda v: clean_words(remove_embedded_labels(v)), min_len=3)
        kecamatan = nearby_value(raw, ["KECAMATAN"], cleaner=lambda v: clean_words(remove_embedded_labels(v)), min_len=3)
        pekerjaan = nearby_value(raw, ["PEKERJAAN"], cleaner=lambda v: clean_words(remove_embedded_labels(v)), min_len=3)
        berlaku_hingga = (
            "SEUMUR HIDUP"
            if semantic_fixed_value(raw, ["SEUMUR HIDUP"], threshold=74)
            else normalize_valid_until(nearby_value(raw, ["BERLAKU HINGGA", "BERLAKU"], cleaner=clean_words, min_len=3))
        )
        kewarganegaraan = (
            semantic_fixed_value(raw, ["WNI", "WNA"], threshold=90)
            or ("WNI" if re.search(r"\bWNI\b", raw, flags=re.IGNORECASE) else ("WNA" if re.search(r"\bWNA\b", raw, flags=re.IGNORECASE) else None))
        )
    else:
        nama = clean_person_name(find_labeled_value(raw, [r"NAMA", r"NAME"]))
        ttl = find_labeled_value(raw, [
            r"TEMPAT\s*/?\s*TGL\.?\s*LAHIR", r"TEMPAT\s*TGL\.?\s*LAHIR",
            r"TEMPATI?\s*TG[LI!1]?\s*LAHIR", r"TEMPAT.*LAHIR",
        ])
        tempat_lahir, tanggal_lahir = split_birth_place_date(ttl)
        jenis_kelamin = normalize_gender(find_labeled_value(raw, [r"JENIS\s*KELAMIN"]))
        alamat = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"ALAMAT", r"ALAMA"])), min_len=5)
        kel_desa = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"KEL\s*/?\s*DESA", r"KELURAHAN", r"DESA"])))
        kecamatan = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"KECAMATAN", r"MECAMATAN"])))
        agama = normalize_religion(find_labeled_value(raw, [r"AGAMA"]))
        status_perkawinan = normalize_marital(find_labeled_value(raw, [r"STATUS\s*PERKAWINAN", r"STATUS"]))
        pekerjaan = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"PEKERJAAN"])))
        kewarganegaraan_raw = find_labeled_value(raw, [r"KEWARGANEGARAAN", r"KEWARGA\s*NEGARAAN"])
        source = f"{kewarganegaraan_raw or ''} {raw}".upper()
        kewarganegaraan = "WNI" if "WNI" in source else ("WNA" if "WNA" in source else None)
        berlaku_hingga = normalize_valid_until(find_labeled_value(raw, [r"BERLAKU\s*HINGGA", r"BERLAKU"]))

    golongan_darah = None
    gol_match = re.search(r"GOL\.?\s*DARAH\s*[:.\-]?\s*(AB|A|B|O|-)", raw, flags=re.IGNORECASE)
    if gol_match:
        golongan_darah = normalize_blood_type(gol_match.group(1))

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


def extract_npwp_fields(text: str, engine_name: str | None = None) -> dict[str, Any]:
    raw = clean_text(text)
    semantic = is_semantic_engine(engine_name)

    npwp15 = get_npwp15(raw)
    npwp16 = get_npwp16(raw)

    if semantic:
        kpp = semantic_kpp(raw)
        nama = (
            nearby_value(raw, ["NAMA WAJIB PAJAK", "WAJIB PAJAK", "NAMA"], cleaner=clean_person_name, min_len=3, prefer_person=True)
            or None
        )
        alamat = nearby_value(raw, ["ALAMAT"], cleaner=lambda v: clean_words(remove_embedded_labels(v), min_len=6), min_len=6)
        kel_kec = nearby_value(raw, ["KELURAHAN KECAMATAN", "KELURAHAN/KECAMATAN", "KEL/KEC", "KELURAHAN", "KECAMATAN"], cleaner=lambda v: clean_words(remove_embedded_labels(v)), min_len=3)
        kab_prov = nearby_value(raw, ["KABUPATEN PROVINSI", "KABUPATEN & PROVINSI", "KABUPATEN DAN PROVINSI", "KABUPATEN", "PROVINSI"], cleaner=lambda v: clean_words(remove_embedded_labels(v)), min_len=3)
        terdaftar_raw = nearby_value(raw, ["TANGGAL TERDAFTAR", "TERDAFTAR"], cleaner=clean_words, min_len=3)
        tanggal_terdaftar = extract_date(terdaftar_raw) or extract_date(raw)
        penerbit = "DJP" if semantic_fixed_value(raw, ["DJP", "DIREKTORAT JENDERAL PAJAK"], threshold=82) else normalize_penerbit(None, raw)
    else:
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
                after = [
                    x for x in lines[i + 1:i + 8]
                    if not re.search(r"NPWP|KPP|TERDAFTAR|PAJAK|DIREKTORAT|DJP", x, flags=re.IGNORECASE)
                ]
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


def extract_from_raw_text(raw_text: str, engine: str | None = None, *, strict: bool = True) -> dict[str, Any]:
    """
    Classify and extract directly from OCR text.

    strict=True returns exactly:
      {"document_type": "...", "fields": {...}}
    strict=False returns the full scoring payload used by the project.
    """
    raw = clean_text(raw_text)
    document_type = detect_document_type(raw)

    if document_type == "KTP":
        fields = extract_ktp_fields(raw, engine)
    elif document_type == "NPWP":
        fields = extract_npwp_fields(raw, engine)
    else:
        fields = {}

    minimal = {"document_type": document_type, "fields": fields}
    if strict:
        return minimal

    return build_single_engine_payload({
        "ocr_status": "success",
        "ocr_engine": engine,
        "ocr_provider": "self-hosted-free",
        "document_type": document_type,
        "extracted_at": now_iso(),
        "fields": fields,
        "raw_text": raw,
    })


def strict_payload_from_run_ocr_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("payload") or {}
    document_type = payload.get("document_type") or result.get("document_type") or "UNKNOWN"
    fields = payload.get("fields") if document_type in ["KTP", "NPWP"] else {}
    if document_type == "KTP":
        fields = order_fields(fields or {}, KTP_FIELD_ORDER)
    elif document_type == "NPWP":
        fields = order_fields(fields or {}, NPWP_FIELD_ORDER)
    else:
        fields = {}
    return {"document_type": document_type, "fields": fields}


def run_ocr_strict(file_path: str, library: str) -> dict[str, Any]:
    """
    File-based OCR that returns only the JSON structure requested by the classifier prompt.
    Keep run_ocr() for DB payloads that need score/raw_text/review metadata.
    """
    return strict_payload_from_run_ocr_result(run_ocr(file_path, library))


# ============================================================
# V3 OVERRIDES: noisy photo handling + NPWP-specific scoring
# These definitions intentionally override earlier functions above.
# ============================================================

OCR_ENABLE_DOCUMENT_CROP = os.getenv("OCR_ENABLE_DOCUMENT_CROP", "1").lower().strip() not in ["0", "false", "no"]
OCR_MAX_IMAGE_DIM = int(os.getenv("OCR_MAX_IMAGE_DIM", "2200"))
OCR_MAX_CROP_CANDIDATES = int(os.getenv("OCR_MAX_CROP_CANDIDATES", "2"))
OCR_CROP_MIN_AREA_RATIO = float(os.getenv("OCR_CROP_MIN_AREA_RATIO", "0.06"))

# NPWP is scored differently from KTP. The formatted "npwp" field is derived
# from npwp15, so it is not scored as a separate field.
NPWP_SCORE_FIELDS = [
    "npwp_number",              # valid npwp15 OR valid npwp16
    "nama",
    "alamat",
    "kelurahan_kecamatan",
    "kabupaten_provinsi",
    "tanggal_terdaftar",
    "kpp",
    "penerbit",
]


def digits_only(value: Any) -> str:
    return re.sub(r"\D", "", repair_digit_text(str(value or "")))


def resize_image_keep_aspect(image: np.ndarray, max_dim: int = OCR_MAX_IMAGE_DIM) -> np.ndarray:
    h, w = image.shape[:2]
    current_max = max(h, w)
    if current_max <= max_dim:
        return image
    scale = max_dim / float(current_max)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def order_quad_points(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype("float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    rect = np.zeros((4, 2), dtype="float32")
    rect[0] = pts[np.argmin(s)]      # top-left
    rect[2] = pts[np.argmax(s)]      # bottom-right
    rect[1] = pts[np.argmin(diff)]   # top-right
    rect[3] = pts[np.argmax(diff)]   # bottom-left
    return rect


def perspective_crop(image: np.ndarray, quad: np.ndarray) -> np.ndarray | None:
    try:
        rect = order_quad_points(quad)
        tl, tr, br, bl = rect
        width_a = np.linalg.norm(br - bl)
        width_b = np.linalg.norm(tr - tl)
        height_a = np.linalg.norm(tr - br)
        height_b = np.linalg.norm(tl - bl)
        max_width = int(max(width_a, width_b))
        max_height = int(max(height_a, height_b))
        if max_width < 200 or max_height < 100:
            return None
        dst = np.array([
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1],
        ], dtype="float32")
        matrix = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(image, matrix, (max_width, max_height))
        return warped
    except Exception:
        return None


def padded_rect_crop(image: np.ndarray, rect: tuple[int, int, int, int], pad_ratio: float = 0.025) -> np.ndarray | None:
    x, y, w, h = rect
    ih, iw = image.shape[:2]
    if w < 200 or h < 100:
        return None
    pad_x = int(w * pad_ratio)
    pad_y = int(h * pad_ratio)
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(iw, x + w + pad_x)
    y2 = min(ih, y + h + pad_y)
    crop = image[y1:y2, x1:x2]
    return crop if crop.size else None


def document_roi_candidates(image: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """
    Returns full image plus likely card/document crops.
    This helps when a KTP/NPWP photo includes a table, chair, hands, or other objects.
    """
    resized = resize_image_keep_aspect(image)
    candidates: list[tuple[str, np.ndarray]] = [("full", resized)]

    if not OCR_ENABLE_DOCUMENT_CROP:
        return candidates

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if len(resized.shape) == 3 else resized.copy()
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    edge_sets = []
    edges = cv2.Canny(gray, 45, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    edge_sets.append(edges)

    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 9
    )
    adaptive = cv2.morphologyEx(adaptive, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=1)
    edge_sets.append(adaptive)

    h, w = gray.shape[:2]
    image_area = float(h * w)
    crop_items: list[tuple[float, str, np.ndarray]] = []

    for edge_image in edge_sets:
        contours, _ = cv2.findContours(edge_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:25]

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < image_area * OCR_CROP_MIN_AREA_RATIO:
                continue

            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
            crop = None
            label = "crop-rect"

            if len(approx) == 4:
                crop = perspective_crop(resized, approx)
                label = "crop-perspective"
            else:
                x, y, cw, ch = cv2.boundingRect(contour)
                if cw <= 0 or ch <= 0:
                    continue
                aspect = max(cw, ch) / max(1, min(cw, ch))
                fill_ratio = area / float(cw * ch)
                # KTP/NPWP cards are usually wider than tall. Use a loose range
                # because camera angle may distort the ratio.
                if 1.15 <= aspect <= 2.55 and fill_ratio >= 0.25:
                    crop = padded_rect_crop(resized, (x, y, cw, ch))

            if crop is None or crop.size == 0:
                continue

            ch, cw = crop.shape[:2]
            if cw < 250 or ch < 140:
                continue

            crop_area = float(cw * ch)
            # Avoid returning almost the same full image as a crop.
            if crop_area > image_area * 0.97:
                continue

            crop_items.append((area, label, crop))

    crop_items.sort(key=lambda item: item[0], reverse=True)
    added = 0
    seen_shapes: set[tuple[int, int]] = set()
    for _area, label, crop in crop_items:
        shape_key = (round(crop.shape[1] / 50) * 50, round(crop.shape[0] / 50) * 50)
        if shape_key in seen_shapes:
            continue
        seen_shapes.add(shape_key)
        candidates.append((f"{label}-{added + 1}", crop))
        added += 1
        if added >= OCR_MAX_CROP_CANDIDATES:
            break

    return candidates


def gray_image(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()


def normalize_contrast(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    return clahe.apply(gray)


def otsu_threshold(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def adaptive_threshold(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 11
    )


def preprocess_variants(image: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """
    Enhanced preprocessing:
    - tries detected card/document crop first when available;
    - uses denoise, CLAHE, sharpen, and threshold variants for blurry/small text.
    """
    variants: list[tuple[str, np.ndarray]] = []
    roi_list = document_roi_candidates(image)

    if OCR_SPEED_MODE == "fast":
        roi_list = roi_list[:2]
    else:
        roi_list = roi_list[: max(1, OCR_MAX_CROP_CANDIDATES + 1)]

    for roi_label, roi in roi_list:
        gray = gray_image(roi)
        gray = resize_image_keep_aspect(gray, max_dim=OCR_MAX_IMAGE_DIM)

        min_side = min(gray.shape[:2])
        scale = 3 if min_side < 500 else 2
        up = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        denoised = cv2.fastNlMeansDenoising(up, None, 10, 7, 21)
        clahe = normalize_contrast(denoised)
        sharp = sharpen_image(clahe)

        variants.append((f"{roi_label}-gray", gray))
        variants.append((f"{roi_label}-upscale-sharp", sharp))

        if OCR_SPEED_MODE != "fast":
            variants.append((f"{roi_label}-clahe", clahe))
            variants.append((f"{roi_label}-otsu", otsu_threshold(sharp)))
            variants.append((f"{roi_label}-adaptive", adaptive_threshold(sharp)))

    # Deduplicate by shape/name enough to reduce repeated OCR calls.
    deduped: list[tuple[str, np.ndarray]] = []
    seen: set[tuple[str, tuple[int, int]]] = set()
    for label, variant in variants:
        key = (label.split("-")[-1], variant.shape[:2])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, variant))
    return deduped


def tesseract_candidate(file_path: str, engine_name: str, use_variants: bool) -> dict[str, Any]:
    images = file_to_images(file_path)
    all_text = []
    configs = ["--oem 3 --psm 6"] if OCR_SPEED_MODE == "fast" else ["--oem 3 --psm 6", "--oem 3 --psm 11", "--oem 3 --psm 4"]

    for page_label, image in images:
        variants = preprocess_variants(image) if use_variants else [("original", image)]
        best_page_text = ""
        best_page_score = -10**9

        for variant_name, variant_image in variants:
            for config in configs:
                cleaned = tesseract_text(variant_image, config)
                current_score = extraction_quality_score(cleaned)

                # Prefer cropped-card OCR when scores are similar, because it usually
                # contains less background noise than the full image.
                if variant_name.startswith("crop"):
                    current_score += 15

                if current_score > best_page_score:
                    best_page_score = current_score
                    best_page_text = cleaned

                doc_type = detect_document_type(cleaned)
                if doc_type in ["KTP", "NPWP"]:
                    fields = extract_ktp_fields(cleaned, engine_name) if doc_type == "KTP" else extract_npwp_fields(cleaned, engine_name)
                    score = calculate_score(doc_type, fields)
                    # Stop early only for near-perfect pages.
                    if score >= max(1, get_max_score(doc_type) - 1):
                        best_page_text = cleaned
                        break
            else:
                continue
            break

        all_text.append(f"--- {page_label} ---\n{best_page_text}")

    raw_text = clean_text("\n".join(all_text))
    document_type = detect_document_type(raw_text)
    fields = extract_ktp_fields(raw_text, engine_name) if document_type == "KTP" else (extract_npwp_fields(raw_text, engine_name) if document_type == "NPWP" else {})

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


def easyocr_candidate(file_path: str) -> dict[str, Any]:
    try:
        import easyocr
    except Exception as exc:
        raise RuntimeError(f"EasyOCR is not installed or failed to load: {exc}")

    reader = easyocr.Reader(["id", "en"], gpu=False, verbose=False)
    images = file_to_images(file_path)
    all_lines = []

    for page_label, image in images:
        best_text = ""
        best_score = -10**9
        for roi_label, roi in document_roi_candidates(image):
            results = reader.readtext(roi, detail=1)
            results.sort(key=lambda x: (x[0][0][1], x[0][0][0]))
            lines = [f"--- {page_label} {roi_label} ---"]
            for _bbox, text, confidence in results:
                if confidence >= 0.18:
                    lines.append(str(text))
            candidate_text = clean_text("\n".join(lines))
            candidate_score = extraction_quality_score(candidate_text)
            if roi_label.startswith("crop"):
                candidate_score += 15
            if candidate_score > best_score:
                best_score = candidate_score
                best_text = candidate_text
        all_lines.append(best_text or f"--- {page_label} ---")

    raw_text = clean_text("\n".join(all_lines))
    document_type = detect_document_type(raw_text)
    fields = extract_ktp_fields(raw_text, "easyocr-local-api") if document_type == "KTP" else (extract_npwp_fields(raw_text, "easyocr-local-api") if document_type == "NPWP" else {})

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
            best_text = ""
            best_score = -10**9
            best_confidences: list[float] = []

            for roi_index, (roi_label, roi) in enumerate(document_roi_candidates(image), start=1):
                temp_path = str(Path(temp_dir) / f"page_{page_index}_{roi_index}.png")
                cv2.imwrite(temp_path, roi)
                result = ocr.ocr(temp_path, cls=True)
                lines = [f"--- {page_label} {roi_label} ---"]
                current_conf: list[float] = []

                for block in result or []:
                    for item in block or []:
                        try:
                            text = item[1][0]
                            conf = float(item[1][1])
                        except Exception:
                            continue
                        if conf >= 0.18:
                            lines.append(str(text))
                            current_conf.append(conf)

                candidate_text = clean_text("\n".join(lines))
                candidate_score = extraction_quality_score(candidate_text)
                if roi_label.startswith("crop"):
                    candidate_score += 15
                if candidate_score > best_score:
                    best_score = candidate_score
                    best_text = candidate_text
                    best_confidences = current_conf

            all_lines.append(best_text or f"--- {page_label} ---")
            confidences.extend(best_confidences)

    raw_text = clean_text("\n".join(all_lines))
    document_type = detect_document_type(raw_text)
    fields = extract_ktp_fields(raw_text, "paddleocr-local-api") if document_type == "KTP" else (extract_npwp_fields(raw_text, "paddleocr-local-api") if document_type == "NPWP" else {})

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


def get_npwp15(text: str) -> str | None:
    repaired = repair_digit_text(text)
    candidates: list[tuple[int, str]] = []
    lines = text_lines(repaired)

    formatted_pattern = r"\b([0-9OIl|!]{2}[.\-\s]?[0-9OIl|!]{3}[.\-\s]?[0-9OIl|!]{3}[.\-\s]?[0-9OIl|!]{1}[.\-\s]?[0-9OIl|!]{3}[.\-\s]?[0-9OIl|!]{3})\b"

    for i, line in enumerate(lines):
        local_text = " ".join(lines[max(0, i - 2): min(len(lines), i + 3)])
        local_bonus = 0
        if re.search(r"NPWP|PAJAK|WAJIB|DJP|KPP", local_text, flags=re.IGNORECASE):
            local_bonus += 25
        for match in re.finditer(formatted_pattern, line, flags=re.IGNORECASE):
            digits = digits_only(match.group(1))
            if len(digits) == 15:
                candidates.append((100 + local_bonus, digits))
        for match in re.finditer(r"\b[0-9OIl|!\s]{15,24}\b", line, flags=re.IGNORECASE):
            digits = digits_only(match.group(0))
            if len(digits) == 15:
                candidates.append((70 + local_bonus, digits))

    # Last fallback: any formatted NPWP in flattened text.
    for match in re.finditer(formatted_pattern, repaired, flags=re.IGNORECASE):
        digits = digits_only(match.group(1))
        if len(digits) == 15:
            candidates.append((60, digits))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def get_npwp16(text: str) -> str | None:
    repaired = repair_digit_text(text)
    candidates: list[tuple[int, str]] = []
    lines = text_lines(repaired)

    for i, line in enumerate(lines):
        local_text = " ".join(lines[max(0, i - 2): min(len(lines), i + 3)])
        local_bonus = 0
        if re.search(r"NPWP\s*16|NIK|16\s*DIGIT|PAJAK|DJP", local_text, flags=re.IGNORECASE):
            local_bonus += 30
        for match in re.finditer(r"\b[0-9OIl|!\s]{16,28}\b", line, flags=re.IGNORECASE):
            digits = digits_only(match.group(0))
            if len(digits) == 16:
                candidates.append((70 + local_bonus, digits))

    if "NPWP" in repaired.upper() or "PAJAK" in repaired.upper():
        for match in re.finditer(r"\b\d{16}\b", re.sub(r"[^\d\s]", " ", repaired)):
            candidates.append((40, match.group(0)))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def detect_document_type(text: str) -> str:
    upper = (text or "").upper()
    ktp_score = 0
    npwp_score = 0

    npwp15 = get_npwp15(text)
    npwp16 = get_npwp16(text)
    ktp_nik = get_ktp_nik(text)

    if npwp15:
        npwp_score += 7
    if npwp16 and re.search(r"NPWP|PAJAK|KPP|DJP", upper):
        npwp_score += 4
    if ktp_nik and not re.search(r"NPWP|PAJAK|KPP|DJP", upper):
        ktp_score += 5

    ktp_keywords = [
        "PROVINSI", "KABUPATEN", "KOTA", "KARTU TANDA PENDUDUK", "NIK",
        "KECAMATAN", "KEL/DESA", "AGAMA", "BERLAKU", "LAKI-LAKI", "PEREMPUAN", "WNI",
    ]
    npwp_keywords = [
        "NPWP", "NPWP16", "KPP", "PRATAMA", "PAJAK", "WAJIB PAJAK",
        "DIREKTORAT JENDERAL PAJAK", "DJP", "TERDAFTAR",
    ]

    for keyword in ktp_keywords:
        if keyword in upper:
            ktp_score += 1
    for keyword in npwp_keywords:
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
        if fuzz.partial_ratio("KARTUTANDAPENDUDUK", key) >= 82:
            ktp_score += 2
        if fuzz.partial_ratio("NPWP", key) >= 82:
            npwp_score += 2
        if fuzz.partial_ratio("WAJIBPAJAK", key) >= 82:
            npwp_score += 2
        if fuzz.partial_ratio("DIREKTORATJENDERALPAJAK", key) >= 82:
            npwp_score += 2

    if npwp_score >= 3 and npwp_score >= ktp_score:
        return "NPWP"
    if ktp_score >= 2:
        return "KTP"
    return "UNKNOWN"


def npwp_number_is_valid(fields: dict[str, Any]) -> bool:
    return is_valid_npwp_field("npwp15", fields.get("npwp15")) or is_valid_npwp_field("npwp16", fields.get("npwp16"))


def is_valid_npwp_field(field: str, value: Any) -> bool:
    if value is None or value == "":
        return False
    value = str(value).upper().strip()

    if field == "npwp15":
        return len(re.sub(r"\D", "", value)) == 15
    if field == "npwp16":
        return len(re.sub(r"\D", "", value)) == 16
    if field == "npwp":
        return bool(re.fullmatch(r"\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}", value))
    if field == "nama":
        return (
            3 <= len(value) <= 100
            and not any(bad in value for bad in ["NPWP", "PAJAK", "ALAMAT", "KPP", "DIREKTORAT", "TERDAFTAR"])
            and bool(re.search(r"[A-Z]", value))
        )
    if field == "alamat":
        return len(value) >= 6 and not any(bad in value for bad in ["NPWP", "KPP", "DIREKTORAT", "TERDAFTAR"])
    if field == "kelurahan_kecamatan":
        return len(value) >= 3 and not any(bad in value for bad in ["NPWP", "DIREKTORAT"])
    if field == "kabupaten_provinsi":
        return len(value) >= 3 and not any(bad in value for bad in ["NPWP", "DIREKTORAT"])
    if field == "tanggal_terdaftar":
        return is_valid_date(value)
    if field == "kpp":
        return len(value) >= 3 and ("KPP" in value or "PRATAMA" in value)
    if field == "penerbit":
        return len(value) >= 2
    return bool(value)


def get_max_score(document_type: str) -> int:
    if document_type == "KTP":
        return len(KTP_SCORE_FIELDS)  # 14
    if document_type == "NPWP":
        return len(NPWP_SCORE_FIELDS)  # 8, separate from KTP
    return 0


def calculate_score(document_type: str, fields: dict[str, Any]) -> int:
    fields = fields or {}
    if document_type == "KTP":
        return sum(1 for field in KTP_SCORE_FIELDS if is_valid_ktp_field(field, fields.get(field)))
    if document_type == "NPWP":
        checks = {
            "npwp_number": npwp_number_is_valid(fields),
            "nama": is_valid_npwp_field("nama", fields.get("nama")),
            "alamat": is_valid_npwp_field("alamat", fields.get("alamat")),
            "kelurahan_kecamatan": is_valid_npwp_field("kelurahan_kecamatan", fields.get("kelurahan_kecamatan")),
            "kabupaten_provinsi": is_valid_npwp_field("kabupaten_provinsi", fields.get("kabupaten_provinsi")),
            "tanggal_terdaftar": is_valid_npwp_field("tanggal_terdaftar", fields.get("tanggal_terdaftar")),
            "kpp": is_valid_npwp_field("kpp", fields.get("kpp")),
            "penerbit": is_valid_npwp_field("penerbit", fields.get("penerbit")),
        }
        return sum(1 for field in NPWP_SCORE_FIELDS if checks.get(field))
    return 0


def get_score_percent(document_type: str, score: int) -> float:
    max_score = get_max_score(document_type)
    return round((score / max_score) * 100, 2) if max_score > 0 else 0.0


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
            not npwp_number_is_valid(fields)
            or not is_valid_npwp_field("nama", fields.get("nama"))
            or score < 5
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
        if not npwp_number_is_valid(fields):
            reasons.append("NPWP number is missing or invalid")
        if not is_valid_npwp_field("nama", fields.get("nama")):
            reasons.append("Nama is missing or invalid")
        if score < 5:
            reasons.append("NPWP score is below acceptance threshold")
    else:
        reasons.append("Document type could not be detected")
    return reasons


def line_has_npwp_number(line: str, npwp15: str | None, npwp16: str | None) -> bool:
    digits = digits_only(line)
    return bool((npwp15 and npwp15 in digits) or (npwp16 and npwp16 in digits))


def is_npwp_noise_line(line: str) -> bool:
    value = normalize_value(line) or ""
    if not value or len(value) < 3:
        return True
    if re.fullmatch(r"[\d\s./\-:]+", value):
        return True
    blocked = [
        "NPWP", "PAJAK", "DIREKTORAT", "DJP", "KPP", "PRATAMA",
        "TERDAFTAR", "PENERBIT", "KARTU", "TAX", "REGISTERED",
    ]
    return any(word in value for word in blocked)


def npwp_block_after_number(raw: str, npwp15: str | None, npwp16: str | None) -> list[str]:
    lines = [normalize_value(x) for x in text_lines(raw)]
    lines = [x for x in lines if x]
    for i, line in enumerate(lines):
        if line_has_npwp_number(line, npwp15, npwp16):
            block = []
            for candidate in lines[i + 1:i + 10]:
                if re.search(r"TANGGAL\s+TERDAFTAR|TERDAFTAR|KPP|DIREKTORAT|DJP", candidate, flags=re.IGNORECASE):
                    break
                if not is_npwp_noise_line(candidate):
                    block.append(candidate)
            return block
    return []


def merge_address_lines(lines: list[str], start_index: int = 1) -> str | None:
    parts = []
    for line in lines[start_index:start_index + 3]:
        clean = clean_words(remove_embedded_labels(line), min_len=3)
        if clean and not is_npwp_noise_line(clean):
            parts.append(clean)
    if not parts:
        return None
    return clean_words(" ".join(parts), min_len=6)


def extract_kpp(raw: str, engine_name: str | None = None) -> str | None:
    lines = text_lines(raw)
    for i, line in enumerate(lines):
        upper = normalize_value(line) or ""
        if re.search(r"\bKPP\b|PRATAMA|KANTOR\s+PELAYANAN\s+PAJAK", upper, flags=re.IGNORECASE):
            merged = upper
            # KPP often splits into two lines: "KPP PRATAMA" / "PEKALONGAN".
            for j in [i + 1, i - 1]:
                if 0 <= j < len(lines):
                    adj = normalize_value(lines[j]) or ""
                    if adj and not re.search(r"NPWP|NAMA|ALAMAT|TERDAFTAR|DIREKTORAT|DJP", adj, flags=re.IGNORECASE):
                        if len(adj) <= 40 and adj not in merged:
                            merged = f"{merged} {adj}"
            merged = re.sub(r"\bKANTOR\s+PELAYANAN\s+PAJAK\b", "KPP", merged, flags=re.IGNORECASE)
            merged = re.sub(r"\s+", " ", merged).strip(" :-_/\\.,")
            if "KPP" not in merged and "PRATAMA" in merged:
                merged = f"KPP {merged}"
            return clean_words(merged, min_len=3)
    return nearby_value(raw, ["KANTOR PELAYANAN PAJAK", "KPP PRATAMA", "KPP"], cleaner=clean_words, min_len=3)


def extract_npwp_fields(text: str, engine_name: str | None = None) -> dict[str, Any]:
    raw = clean_text(text)
    semantic = is_semantic_engine(engine_name)

    npwp15 = get_npwp15(raw)
    npwp16 = get_npwp16(raw)
    number_block = npwp_block_after_number(raw, npwp15, npwp16)

    kpp = extract_kpp(raw, engine_name)

    if semantic:
        nama = nearby_value(raw, ["NAMA WAJIB PAJAK", "WAJIB PAJAK", "NAMA"], cleaner=clean_person_name, min_len=3, prefer_person=True)
        alamat = nearby_value(raw, ["ALAMAT"], cleaner=lambda v: clean_words(remove_embedded_labels(v), min_len=6), min_len=6)
        kel_kec = nearby_value(raw, ["KELURAHAN KECAMATAN", "KELURAHAN/KECAMATAN", "KEL/KEC", "KELURAHAN", "KECAMATAN"], cleaner=lambda v: clean_words(remove_embedded_labels(v)), min_len=3)
        kab_prov = nearby_value(raw, ["KABUPATEN PROVINSI", "KABUPATEN & PROVINSI", "KABUPATEN DAN PROVINSI", "KABUPATEN", "PROVINSI"], cleaner=lambda v: clean_words(remove_embedded_labels(v)), min_len=3)
        terdaftar_raw = nearby_value(raw, ["TANGGAL TERDAFTAR", "TERDAFTAR"], cleaner=clean_words, min_len=3)
        tanggal_terdaftar = extract_date(terdaftar_raw) or extract_date(raw)
        penerbit = "DJP" if semantic_fixed_value(raw, ["DJP", "DIREKTORAT JENDERAL PAJAK"], threshold=82) else normalize_penerbit(None, raw)
    else:
        nama = clean_person_name(find_labeled_value(raw, [r"NAMA\s+WAJIB\s+PAJAK", r"WAJIB\s+PAJAK", r"NAMA"]))
        alamat = clean_words(remove_embedded_labels(find_labeled_value(raw, [r"ALAMAT"])), min_len=6)
        kel_kec = find_labeled_value(raw, [r"KELURAHAN\s*/\s*KECAMATAN", r"KEL\s*/\s*KEC", r"KELURAHAN", r"KECAMATAN"])
        kel_kec = clean_words(remove_embedded_labels(kel_kec), min_len=3)
        kab_prov = find_labeled_value(raw, [r"KABUPATEN\s*&\s*PROVINSI", r"KABUPATEN\s+DAN\s+PROVINSI", r"KAB\.?\s*&\s*PROV", r"KABUPATEN", r"PROVINSI"])
        kab_prov = clean_words(remove_embedded_labels(kab_prov), min_len=3)
        terdaftar_raw = find_labeled_value(raw, [r"TANGGAL\s+TERDAFTAR", r"TERDAFTAR"])
        tanggal_terdaftar = extract_date(terdaftar_raw) or extract_date(raw)
        penerbit = normalize_penerbit(find_labeled_value(raw, [r"PENERBIT", r"DIREKTORAT\s+JENDERAL\s+PAJAK", r"DJP"]), raw)

    # Strong fallback for common NPWP card layout: number line, then name, then address.
    if number_block:
        if not nama and number_block:
            nama = clean_person_name(number_block[0])
        if not alamat and len(number_block) >= 2:
            alamat = merge_address_lines(number_block, 1)
        if not kel_kec:
            for line in number_block:
                if re.search(r"KEL|KEC|DESA|KELURAHAN|KECAMATAN", line, flags=re.IGNORECASE):
                    kel_kec = clean_words(remove_embedded_labels(line), min_len=3)
                    break
        if not kab_prov:
            for line in number_block:
                if re.search(r"KAB|KOTA|PROV", line, flags=re.IGNORECASE):
                    kab_prov = clean_words(remove_embedded_labels(line), min_len=3)
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
        "score_max": score_max,
        "score_percent": get_score_percent(document_type, score),
        "fields": fields,
        "raw_text": candidate.get("raw_text", ""),
        "ocr_engine": candidate.get("ocr_engine"),
        "ocr_status": candidate.get("ocr_status", "success"),
        "ocr_enabled": True,
        "extracted_at": candidate.get("extracted_at", now_iso()),
        "ocr_provider": candidate.get("ocr_provider", "self-hosted-free"),
        "document_type": document_type,
        "review_reasons": review_reasons(document_type, fields, score) if manual_review_required else [],
        "manual_review_required": manual_review_required,
    }

    if candidate.get("confidence_avg") is not None:
        payload["confidence_avg"] = candidate.get("confidence_avg")
    if candidate.get("error"):
        payload["error"] = candidate.get("error")
    return payload


def extract_from_raw_text(raw_text: str, engine: str | None = None, *, strict: bool = True) -> dict[str, Any]:
    raw = clean_text(raw_text)
    document_type = detect_document_type(raw)

    if document_type == "KTP":
        fields = extract_ktp_fields(raw, engine)
    elif document_type == "NPWP":
        fields = extract_npwp_fields(raw, engine)
    else:
        fields = {}

    score = calculate_score(document_type, fields)
    score_max = get_max_score(document_type)

    clean_payload = {
        "document_type": document_type,
        "score": score,
        "score_max": score_max,
        "score_percent": get_score_percent(document_type, score),
        "fields": fields,
    }

    if strict:
        return clean_payload

    return build_single_engine_payload({
        "ocr_status": "success",
        "ocr_engine": engine,
        "ocr_provider": "self-hosted-free",
        "document_type": document_type,
        "extracted_at": now_iso(),
        "fields": fields,
        "raw_text": raw,
    })


def strict_payload_from_run_ocr_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("payload") or {}
    document_type = payload.get("document_type") or result.get("document_type") or "UNKNOWN"
    fields = payload.get("fields") if document_type in ["KTP", "NPWP"] else {}
    if document_type == "KTP":
        fields = order_fields(fields or {}, KTP_FIELD_ORDER)
    elif document_type == "NPWP":
        fields = order_fields(fields or {}, NPWP_FIELD_ORDER)
    else:
        fields = {}
    score = calculate_score(document_type, fields)
    return {
        "document_type": document_type,
        "score": score,
        "score_max": get_max_score(document_type),
        "score_percent": get_score_percent(document_type, score),
        "fields": fields,
    }


def run_ocr_strict(file_path: str, library: str) -> dict[str, Any]:
    return strict_payload_from_run_ocr_result(run_ocr(file_path, library))
