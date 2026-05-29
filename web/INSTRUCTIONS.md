# OCR Dashboard - Project Instructions

## Project Overview
Single-page OCR admin dashboard for managing Optical Character Recognition operations with support for multiple OCR engines.

---

## Project Structure

```
OCR_shortproject/
├── index.html                 # Main entry point (SPA router)
├── components/                # UI components
│   ├── header.html           # Top navigation bar
│   ├── sidebar.html          # Left navigation menu
│   ├── view-home.html        # Dashboard home view
│   └── view-ocr.html         # OCR management view
├── controllers/               # jQuery AJAX controllers for backend communication
│   └── [backend handlers].js
├── lib/                       # External JavaScript libraries
│   ├── chart.js              # Chart rendering
│   ├── datatables.js         # Data table functionality
│   ├── jquery-3.7.js         # DOM manipulation
│   ├── litepicker.js         # Date range picker
│   ├── lucide.js             # Icon library
│   └── sweetalert2.js        # Alert dialogs
└── assets/                    # Stylesheets & fonts
    ├── css/                  # Tailwind, FontAwesome, and custom styles
    └── webfonts/             # Icon fonts
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend Framework** | jQuery (DOM manipulation) |
| **CSS Framework** | Tailwind CSS (responsive styling) |
| **Icons** | Font Awesome 6 |
| **Alerts** | SweetAlert2 |
| **Tables** | DataTables |
| **Charts** | Chart.js |
| **Date Picker** | LitePicker |

---

## How It Works

### 1. **Page Load Flow**
```
index.html loads
  ├─> Loads sidebar.html (#sidebar-container)
  ├─> Loads header.html (#header-container)
  └─> Routes to default view: loadView('home')
```

### 2. **Navigation & Routing**
- **SPA Router**: `loadView()` function handles view switching
- **Routes**:
  - `home` → `components/view-home.html`
  - `ocr` → `components/view-ocr.html`
- Navigation triggered by sidebar links (`#nav-home`, `#nav-ocr`)

### 3. **User Interaction Flow** (Example: OCR Upload)
```
User selects OCR library & files
  ↓
Form submission (id="ocr-upload-form")
  ↓
jQuery event handler (controllers/[handler].js)
  ↓
AJAX POST to backend API
  ↓
Backend processes OCR
  ↓
SweetAlert2 shows success/error
  ↓
DataTables updates processed results table
```

### 4. **Backend Communication**
- **Location**: `controllers/` directory
- **Method**: jQuery AJAX ($.ajax, $.post)
- **Purpose**: Handle form submissions and fetch data from backend
- **Example**: OCR upload → sends files to backend → receives processing results

---

## File Responsibilities

| File | Responsibility |
|------|-----------------|
| `controllers/*.js` | AJAX calls, form handlers, backend API communication |
| `lib/*.js` | Third-party dependencies (read-only) |
| `components/*.html` | UI markup and structure |
| `assets/css/` | Styling (Tailwind + custom) |

---

## Adding a New Feature

1. **Create UI Component**: Add new `.html` file in `components/`
2. **Add Route**: Update `loadView()` in `index.html`
3. **Create Controller**: Add AJAX handler in `controllers/[feature].js`
4. **Add Navigation Link**: Update `sidebar.html`
5. **Style**: Use Tailwind classes or add custom CSS in `assets/css/`

---

## Key Notes
- Fully responsive design using Tailwind CSS
- All JavaScript operations handled via jQuery
- Components are modular and loaded dynamically
- Backend API endpoints to be defined in controllers
- No build process required (vanilla setup)
