import json
import uuid
from pathlib import Path
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

from . import config
from .db import insert_upload_file, list_files, get_file, delete_file
from .ocr_engine import ensure_upload_dir

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

ensure_upload_dir()


def response(status=True, message="OK", data=None, http_status=200):
    return jsonify({"status": status, "message": message, "data": data}), http_status


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in config.ALLOWED_EXTENSIONS


def make_file_id() -> str:
    return "OCR-" + datetime.utcnow().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8].upper()


@app.get("/api/health")
def health():
    return response(True, "Backend is running", {"service": "ocr-backend"})


@app.post("/api/ocr/upload")
def upload_ocr_files():
    # Frontend can send either files[] or file-input. We support both.
    files = request.files.getlist("files[]") or request.files.getlist("files") or request.files.getlist("file-input")
    ocr_library = request.form.get("ocr_library") or request.form.get("library") or "hybrid-field-merge"

    if not files:
        return response(False, "No files uploaded", None, 400)

    saved = []
    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename):
            return response(False, f"File type not allowed: {f.filename}", None, 400)

        file_id = make_file_id()
        safe_original = secure_filename(f.filename)
        ext = Path(safe_original).suffix.lower()
        stored_name = f"{file_id}{ext}"
        abs_path = config.UPLOAD_DIR / stored_name
        f.save(abs_path)

        # Store relative path so frontend can open it regardless of server root.
        rel_path = f"uploads/{stored_name}"
        insert_upload_file(file_id, safe_original, rel_path)
        saved.append({
            "id": file_id,
            "filename": safe_original,
            "filepath": rel_path,
            "status": "queued",
            "requested_library": ocr_library,
        })

    return response(True, "OCR job created", saved, 201)


@app.get("/api/ocr/files")
def get_files():
    rows = list_files()
    for row in rows:
        if row.get("json_payload"):
            try:
                payload = json.loads(row["json_payload"])
                row["ocr_engine"] = payload.get("ocr_engine")
                row["document_type"] = payload.get("document_type")
                row["manual_review_required"] = payload.get("manual_review_required")
            except Exception:
                pass
        row["createdAt"] = row["createdAt"].isoformat() if row.get("createdAt") else None
        row["processedAt"] = row["processedAt"].isoformat() if row.get("processedAt") else None
    return response(True, "Files loaded", rows)


@app.get("/api/ocr/files/<file_id>")
def get_file_detail(file_id):
    row = get_file(file_id)
    if not row:
        return response(False, "File not found", None, 404)
    if row.get("json_payload"):
        try:
            row["json_payload"] = json.loads(row["json_payload"])
        except Exception:
            pass
    row["createdAt"] = row["createdAt"].isoformat() if row.get("createdAt") else None
    row["processedAt"] = row["processedAt"].isoformat() if row.get("processedAt") else None
    return response(True, "File detail loaded", row)


@app.delete("/api/ocr/files/<file_id>")
def delete_file_row(file_id):
    row = get_file(file_id)
    if not row:
        return response(False, "File not found", None, 404)
    affected = delete_file(file_id)
    # Keep physical files by default for audit safety. Delete manually if required.
    return response(True, "File deleted from database", {"affected": affected})


@app.get("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(str(config.UPLOAD_DIR), filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088, debug=True)
