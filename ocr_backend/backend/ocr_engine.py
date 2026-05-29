import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image
import fitz  # PyMuPDF

from . import config
from .extractors import (
    extract_ktp,
    extract_npwp,
    detect_document_type,
    normalize_text,
    score_fields,
    KTP_FIELDS,
    NPWP_FIELDS,
)

_paddle_ocr = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_upload_dir():
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def file_to_images(file_path: str) -> List[np.ndarray]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if path.suffix.lower() == ".pdf":
        images = []
        doc = fitz.open(str(path))
        try:
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
                else:
                    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                images.append(img)
        finally:
            doc.close()
        return images

    image = cv2.imread(str(path))
    if image is None:
        # PIL fallback for webp/tiff edge cases
        pil = Image.open(str(path)).convert("RGB")
        image = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return [image]


def preprocess_variants(image: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    variants = []
    h, w = image.shape[:2]
    scale = max(1.0, 1600 / max(w, h))
    resized = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    variants.append(("gray", gray))
    variants.append(("denoised", denoised))

    sharp_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharp = cv2.filter2D(denoised, -1, sharp_kernel)
    variants.append(("sharp", sharp))

    thresh = cv2.adaptiveThreshold(
        sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    variants.append(("threshold", thresh))

    return variants


def run_tesseract(images: List[np.ndarray]) -> Dict[str, Any]:
    pages = []
    best_text = ""
    for idx, img in enumerate(images, start=1):
        page_candidates = []
        for name, variant in preprocess_variants(img):
            text = pytesseract.image_to_string(
                variant,
                lang=config.TESSERACT_LANG,
                config="--oem 3 --psm 6",
            )
            text = normalize_text(text)
            page_candidates.append(text)
        chosen = max(page_candidates, key=lambda x: len(x or "")) if page_candidates else ""
        pages.append(f"--- PDF PAGE {idx} ---\n{chosen}" if len(images) > 1 else chosen)
    best_text = normalize_text("\n".join(pages))
    return build_candidate("tesseract-local-cli", best_text)


def get_paddle():
    global _paddle_ocr
    if _paddle_ocr is None:
        from paddleocr import PaddleOCR
        _paddle_ocr = PaddleOCR(use_angle_cls=True, lang=config.PADDLE_LANG, show_log=False)
    return _paddle_ocr


def run_paddleocr(images: List[np.ndarray]) -> Dict[str, Any]:
    ocr = get_paddle()
    page_texts = []
    confidences = []
    for idx, img in enumerate(images, start=1):
        # Paddle accepts ndarray. Use original-sized image because Paddle handles detection itself.
        result = ocr.ocr(img, cls=True)
        lines = []
        for page in result or []:
            for item in page or []:
                if not item or len(item) < 2:
                    continue
                text, conf = item[1][0], float(item[1][1])
                lines.append(str(text))
                confidences.append(conf)
        body = normalize_text("\n".join(lines))
        page_texts.append(f"--- PAGE {idx} ---\n{body}" if len(images) > 1 else body)

    raw_text = normalize_text("\n".join(page_texts))
    candidate = build_candidate("paddleocr-local-api", raw_text)
    if confidences:
        candidate["confidence_avg"] = round(sum(confidences) / len(confidences), 4)
    return candidate


def run_opencv_ocr(images: List[np.ndarray]) -> Dict[str, Any]:
    """OpenCV is preprocessing, then Tesseract reads the enhanced result."""
    pages = []
    for idx, img in enumerate(images, start=1):
        variants = preprocess_variants(img)
        # Prefer threshold variant for OpenCV-enhanced run.
        variant = variants[-1][1]
        text = pytesseract.image_to_string(
            variant,
            lang=config.TESSERACT_LANG,
            config="--oem 3 --psm 4",
        )
        pages.append(f"--- OPENCV PAGE {idx} ---\n{normalize_text(text)}" if len(images) > 1 else normalize_text(text))
    return build_candidate("opencv-preprocess-tesseract", normalize_text("\n".join(pages)))


def build_candidate(engine_name: str, raw_text: str) -> Dict[str, Any]:
    ktp_fields, ktp_quality = extract_ktp(raw_text)
    npwp_fields, npwp_quality = extract_npwp(raw_text)
    document_type = detect_document_type(raw_text, ktp_fields, npwp_fields)

    if document_type == "NPWP":
        fields = npwp_fields
        quality = npwp_quality
    else:
        fields = ktp_fields
        quality = ktp_quality

    return {
        "ocr_enabled": True,
        "ocr_status": "success",
        "ocr_engine": engine_name,
        "ocr_provider": "self-hosted-free",
        "document_type": document_type,
        "extracted_at": now_iso(),
        "fields": fields,
        "raw_text": raw_text,
        "score": score_fields(fields, quality),
        "field_quality_scores": quality,
    }


def empty_fields_for_type(document_type: str) -> Dict[str, Any]:
    return dict(NPWP_FIELDS if document_type == "NPWP" else KTP_FIELDS)


def merge_candidates(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = [c for c in candidates if c.get("ocr_status") == "success"]
    if not valid:
        raise RuntimeError("No OCR candidate succeeded")

    selected = max(valid, key=lambda c: c.get("score", 0))
    document_type = selected.get("document_type") or "KTP"

    # If candidates disagree, choose majority by score-weighted evidence.
    doc_scores = {"KTP": 0, "NPWP": 0}
    for c in valid:
        dt = c.get("document_type")
        if dt in doc_scores:
            doc_scores[dt] += int(c.get("score", 0)) + 1
    document_type = "NPWP" if doc_scores["NPWP"] > doc_scores["KTP"] else "KTP"

    field_template = empty_fields_for_type(document_type)
    merged_fields = dict(field_template)
    field_sources = {}
    field_quality_scores = {}

    for field in field_template:
        best_value = None
        best_engine = None
        best_quality = -1
        for c in valid:
            if c.get("document_type") != document_type:
                continue
            value = (c.get("fields") or {}).get(field)
            quality = int((c.get("field_quality_scores") or {}).get(field, 0))
            if value and quality > best_quality:
                best_value = value
                best_quality = quality
                best_engine = c.get("ocr_engine")
        merged_fields[field] = best_value
        if best_value:
            field_sources[field] = best_engine
            field_quality_scores[field] = best_quality
        else:
            field_quality_scores[field] = 0

    manual_review_required = any(v is None for v in merged_fields.values()) or any(
        score < 60 for k, score in field_quality_scores.items() if merged_fields.get(k)
    )

    raw_text = selected.get("raw_text") or ""
    payload = {
        "ocr_enabled": True,
        "ocr_status": "success",
        "ocr_engine": "hybrid-field-merge",
        "ocr_provider": "self-hosted-free",
        "document_type": document_type,
        "extracted_at": now_iso(),
        "fields": merged_fields,
        "raw_text": raw_text,
        "score": score_fields(merged_fields, field_quality_scores),
        "ocr_selected_candidate_engine": selected.get("ocr_engine"),
        "field_sources": field_sources,
        "field_quality_scores": field_quality_scores,
        "ocr_candidates": valid,
        "manual_review_required": manual_review_required,
    }
    if "confidence_avg" in selected:
        payload["confidence_avg"] = selected["confidence_avg"]
    return payload


def process_file(file_path: str, requested_library: str | None = None) -> Dict[str, Any]:
    images = file_to_images(file_path)
    candidates = []
    errors = []

    # Run all local engines for hybrid field merge.
    runners = [run_tesseract, run_paddleocr, run_opencv_ocr]
    for runner in runners:
        try:
            candidates.append(runner(images))
        except Exception as exc:
            errors.append({
                "engine": runner.__name__,
                "error": str(exc),
                "trace": traceback.format_exc(),
            })

    payload = merge_candidates(candidates)
    if errors:
        payload["ocr_engine_errors"] = errors
    if requested_library:
        payload["requested_library"] = requested_library
    return payload


def build_failed_payload(error: str) -> Dict[str, Any]:
    return {
        "ocr_enabled": True,
        "ocr_status": "failed",
        "ocr_engine": "hybrid-field-merge",
        "ocr_provider": "self-hosted-free",
        "document_type": None,
        "extracted_at": now_iso(),
        "fields": {},
        "raw_text": "",
        "score": 0,
        "error_message": error,
        "manual_review_required": True,
    }


def dumps_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
