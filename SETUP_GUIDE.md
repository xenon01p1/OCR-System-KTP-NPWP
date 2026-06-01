# OCR Dashboard - Complete Setup Guide

## Full System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     USER BROWSER                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Frontend: jQuery + Tailwind CSS                      │   │
│  │  - Upload OCR files                                  │   │
│  │  - Select OCR library                               │   │
│  │  - View results in real-time                        │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────┬────────────────────────────────────────────┘
                 │ HTTP API (Port 8060)
                 ↓
┌─────────────────────────────────────────────────────────────┐
│              PYTHON FLASK API SERVER                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  app.py - Main API                                   │   │
│  │  ├─ POST /api/ocr/upload (Queue files)             │   │
│  │  ├─ GET /api/ocr/files (List jobs)                 │   │
│  │  └─ GET /api/ocr/job/<id> (Get details)           │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────┬────────────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        ↓                 ↓
    MySQL DB      Background Thread
    (Results)    (ocr_processor.py)
    ├─ Jobs     - Fetches from queue
    └─ Queue    - Processes with OCR
               - Saves results
               - Runs continuously
```

---

## Project Structure (Complete)

```
OCR_shortproject/
│
├── index.html                      # Main entry point (SPA)
│
├── components/                     # Frontend UI components
│   ├── header.html
│   ├── sidebar.html
│   ├── view-home.html
│   └── view-ocr.html               # OCR upload form
│
├── controllers/                    # Frontend jQuery handlers
│   └── view-ocr.js                 # AJAX calls to backend
│
├── lib/                            # JavaScript libraries
│   ├── jquery-3.7.js
│   ├── chart.js
│   ├── datatables.js
│   ├── sweetalert2.js
│   └── lucide.js
│
├── assets/                         # Styles & fonts
│   ├── css/
│   │   └── tailwind.css
│   └── webfonts/
│
├── INSTRUCTIONS.md                 # Project documentation
│
└── backend/                        # Python Backend Service ⭐
    ├── app.py                      # Flask API server
    ├── config.py                   # Configuration
    ├── database.py                 # MySQL operations
    ├── ocr_processor.py            # Background processing
    ├── ocr_engines.py              # OCR implementations
    ├── requirements.txt            # Python dependencies
    ├── .env.example                # Config template
    ├── startup.bat                 # Windows launcher
    ├── startup.sh                  # Linux/Mac launcher
    ├── README.md                   # Backend docs
    └── uploads/                    # Uploaded files (auto-created)
```

---

## Quick Start

### Step 1: Setup Python Backend

```bash
cd backend
```

### Step 2: Create Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your MySQL credentials:
# MYSQL_HOST=localhost
# MYSQL_USER=root
# MYSQL_PASSWORD=your_password
# MYSQL_DATABASE=ocr_db
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Start the Backend Service

**Windows:**
```bash
startup.bat
```

**Linux/Mac:**
```bash
chmod +x startup.sh
./startup.sh
```

You should see:
```
Starting OCR API Server on port 8060...
OCR Processor started
 * Running on http://127.0.0.1:8060
```

### Step 5: Open Frontend

1. Open `index.html` in your browser (or use a local web server)
2. Navigate to **OCR Management** tab
3. Select an OCR library
4. Upload files
5. Watch the processing status update in real-time

---

## How It Works - Step by Step

### 1️⃣ User Uploads Files
```
Frontend (view-ocr.html)
  ↓
User selects OCR library (Tesseract, Google Vision, AWS Textract, PaddleOCR)
User selects files (PDF, PNG, JPG)
User clicks "Run Engine Process"
```

### 2️⃣ Frontend Sends to Backend
```
jQuery AJAX (view-ocr.js)
  ↓
POST /api/ocr/upload
  - ocr_library: "Tesseract OCR"
  - files[]: [file1, file2, file3]
```

### 3️⃣ Backend Queues Jobs
```
Flask Server (app.py)
  ↓
Create job records in MySQL (ocr_jobs table)
Add jobs to processing queue (ocr_queue table)
Return job IDs to frontend
```

### 4️⃣ Background Processor Runs
```
OCR Processor (ocr_processor.py)
  ↓
Continuously loop:
  1. Check ocr_queue for next job
  2. If job exists:
     - Update status to 'processing'
     - Call OCR engine (ocr_engines.py)
     - Save extracted text to database
     - Update status to 'success'
  3. If no jobs: wait 2 seconds
```

### 5️⃣ Frontend Polls Results
```
jQuery polling (every 5 seconds)
  ↓
GET /api/ocr/files
  ↓
Display updated status in table:
  - queued → processing → success
  - Show extracted text when complete
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Frontend** | HTML5, jQuery, Tailwind CSS, Font Awesome |
| **Backend API** | Python Flask, Flask-CORS |
| **Database** | MySQL |
| **Background Job** | Python threading |
| **OCR Engines** | Tesseract, Google Vision, AWS Textract, PaddleOCR |
| **Communication** | HTTP REST API |

---

## Frontend Controller (view-ocr.js)

Located at: `controllers/view-ocr.js`

Key functions:
- `bindOcrPageEvents()` - Attach event handlers
- `loadOcrFiles()` - Fetch job list from backend
- `statusBadge()` - Format status display

API endpoint: `http://127.0.0.1:8060/api`

---

## Backend Files Explained

| File | Purpose |
|------|---------|
| `app.py` | Flask API server - handles HTTP requests |
| `config.py` | Configuration management - reads .env file |
| `database.py` | MySQL operations - CRUD for jobs |
| `ocr_processor.py` | Background thread - processes queue continuously |
| `ocr_engines.py` | OCR implementations - calls Tesseract, Google, AWS, PaddleOCR |
| `requirements.txt` | Python package dependencies |

---

## Database Tables

### ocr_jobs
```
id: 1
job_id: abc-def-ghi (UUID)
filename: document.pdf
ocr_library: Tesseract OCR
status: success
extracted_text: "Lorem ipsum dolor sit..."
processing_time_ms: 1234
created_at: 2024-05-29 10:30:00
```

### ocr_queue
```
id: 1
job_id: abc-def-ghi
file_path: /backend/uploads/abc123_document.pdf
ocr_library: Tesseract OCR
created_at: 2024-05-29 10:30:00
```

---

## Supported OCR Libraries

### 1. Tesseract OCR (Open Source)
- **Best for**: Simple documents, English text, offline use
- **Speed**: Fast
- **Installation**: Extra setup required (see backend README)
- **Cost**: Free

### 2. Google Cloud Vision API
- **Best for**: High accuracy, multilingual, complex layouts
- **Speed**: Depends on API response
- **Setup**: Requires Google Cloud credentials
- **Cost**: Pay per request

### 3. AWS Textract
- **Best for**: Forms, tables, structured documents
- **Speed**: Depends on API response
- **Setup**: Requires AWS credentials
- **Cost**: Pay per request

### 4. PaddleOCR (Open Source)
- **Best for**: Multilingual, Asian characters, offline use
- **Speed**: Good
- **Installation**: Automatic with pip
- **Cost**: Free

---

## API Endpoints

### Check Health
```
GET http://localhost:8060/health
Response: { "status": "ok", "service": "OCR API Server" }
```

### Upload Files
```
POST http://localhost:8060/api/ocr/upload
Content-Type: multipart/form-data

Body:
- ocr_library: "Tesseract OCR"
- files[]: [multiple files]

Response:
{
  "message": "Successfully queued 3 file(s)",
  "count": 3,
  "jobs": [
    { "job_id": "uuid", "filename": "doc.pdf" }
  ]
}
```

### Get All Jobs
```
GET http://localhost:8060/api/ocr/files?limit=50

Response:
{
  "count": 50,
  "jobs": [
    {
      "id": 1,
      "job_id": "uuid",
      "filename": "doc.pdf",
      "status": "success",
      "text": "Extracted text...",
      "processing_time_ms": 1234
    }
  ]
}
```

### Get Job Details
```
GET http://localhost:8060/api/ocr/job/{job_id}

Response:
{
  "job_id": "uuid",
  "status": "success",
  "text": "Full extracted text content...",
  "processing_time_ms": 1234
}
```

---

## Troubleshooting

### Backend won't start
```bash
# Check if port 8060 is in use
netstat -ano | findstr :8060  # Windows
lsof -i :8060                  # Mac/Linux

# Update port in .env
PORT=8070
```

### MySQL connection fails
```
Check .env credentials:
- MYSQL_HOST
- MYSQL_USER
- MYSQL_PASSWORD
- MYSQL_DATABASE

Verify MySQL is running and database exists
```

### OCR returns no text
- File format might not be supported
- Image quality too low
- OCR engine not installed (for Tesseract)

### Slow processing
- Use SSD storage for uploads folder
- Reduce MAX_FILE_SIZE in .env
- Use faster OCR (Tesseract) vs Cloud (Google/AWS)

---

## Performance Considerations

1. **Background Thread**: Runs continuously without blocking API
2. **Queue System**: Jobs processed FIFO (first in, first out)
3. **Database Indexing**: Fast lookups on status and date
4. **File Cleanup**: Delete old uploads periodically to save space
5. **Concurrent Uploads**: Frontend can upload while backend processes

---

## Adding a New Feature

Example: Add ability to delete jobs

1. **Backend** (database.py):
   ```python
   def delete_job(self, job_id):
       """Delete job and remove from queue"""
   ```

2. **Backend** (app.py):
   ```python
   @app.route('/api/ocr/job/<job_id>', methods=['DELETE'])
   def delete_job(job_id):
       ...
   ```

3. **Frontend** (view-ocr.js):
   ```javascript
   $.ajax({
       url: `${OCR_API_BASE}/ocr/job/${job_id}`,
       method: 'DELETE',
       ...
   });
   ```

---

## Next Steps

1. ✅ Start backend service
2. ✅ Verify API is accessible (visit `/health`)
3. ✅ Test file upload
4. ✅ Monitor processing in MySQL
5. ✅ View results in frontend

**Refer to** `backend/README.md` **for detailed backend documentation**
