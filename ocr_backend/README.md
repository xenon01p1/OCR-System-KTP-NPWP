# OCR Backend

Backend for KTP/NPWP OCR using local/free OCR engines:

- PaddleOCR
- Tesseract OCR
- OpenCV preprocessing + Tesseract

The API inserts uploaded files into the existing `upload_files` table. The worker runs forever, claims `queued` rows, processes OCR, and updates `json_payload`.

## Install

```bash
cd /var/www/html/OCR_shortproject
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
sudo apt update
sudo apt install -y tesseract-ocr tesseract-ocr-ind
cp .env.example .env
```

Import your `ocr.sql` into MySQL before running.

## Run manually

Terminal 1:

```bash
source venv/bin/activate
python run_api.py
```

Terminal 2:

```bash
source venv/bin/activate
python run_worker.py
```

## API

### Upload

```http
POST /api/ocr/upload
Content-Type: multipart/form-data

files[] = file(s)
ocr_library = PaddleOCR / Tesseract OCR / hybrid-field-merge
```

### List

```http
GET /api/ocr/files
```

### Detail

```http
GET /api/ocr/files/{id}
```

### Delete

```http
DELETE /api/ocr/files/{id}
```

## Systemd

Copy service files:

```bash
sudo cp systemd/ocr-api.service /etc/systemd/system/ocr-api.service
sudo cp systemd/ocr-worker.service /etc/systemd/system/ocr-worker.service
sudo systemctl daemon-reload
sudo systemctl enable ocr-api ocr-worker
sudo systemctl start ocr-api ocr-worker
```

Logs:

```bash
journalctl -u ocr-api -f
journalctl -u ocr-worker -f
```
