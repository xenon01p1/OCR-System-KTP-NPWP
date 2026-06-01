# Quick Reference - OCR Backend Service

## Start Backend (Windows)
```
cd backend
startup.bat
```

## Start Backend (Linux/Mac)
```
cd backend
chmod +x startup.sh
./startup.sh
```

## Configuration File
- Edit: `backend/.env`
- Required: MySQL credentials
- Optional: Google/AWS API keys

## API Endpoints (Running on http://localhost:8060)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Check if service is running |
| POST | `/api/ocr/upload` | Upload files for OCR |
| GET | `/api/ocr/files` | Get all jobs & results |
| GET | `/api/ocr/job/{id}` | Get specific job details |

## Frontend Integration
- Already configured in: `controllers/view-ocr.js`
- API Base: `http://127.0.0.1:8060/api`
- Polls every 5 seconds for updates

## Database
- Auto-creates tables on first run
- Tables: `ocr_jobs`, `ocr_queue`
- MySQL credentials in `backend/.env`

## Supported OCR Libraries
1. Tesseract OCR (Open Source)
2. Google Vision API (Cloud)
3. AWS Textract (Cloud)
4. PaddleOCR (Open Source)

## How It Works
1. User uploads files + selects OCR library
2. Frontend sends to backend API
3. Backend queues jobs in MySQL
4. Background processor runs continuously
5. Extracts text and stores in database
6. Frontend polls and displays results

## File Structure
```
backend/
├── app.py (Flask API)
├── database.py (MySQL)
├── ocr_processor.py (Background worker)
├── ocr_engines.py (OCR implementations)
├── config.py (Config management)
├── requirements.txt (Dependencies)
├── .env (Configuration)
├── startup.bat/sh (Launch script)
└── uploads/ (Uploaded files)
```

## Dependencies to Install
```bash
pip install -r requirements.txt
```

## Troubleshooting
- Port 8060 in use? → Change PORT in .env
- MySQL won't connect? → Check credentials in .env
- No text extracted? → Verify file format (PDF/PNG/JPG)
- Tesseract error? → Install Tesseract engine separately
