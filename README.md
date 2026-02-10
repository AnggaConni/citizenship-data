# 🌍 Global Biodiversity & Biosphere 2026 (BioSphere)

**BioSphere** is a progressive Web GIS (Geographic Information System) application designed to visualize, monitor, and manage Biodiversity and Biosphere Reserve data. The application is built using a serverless architecture, with Google Sheets acting as the primary database.

### Key Features

#### 1. Interactive Map (GIS)

- Multi-Layer Visualization: Displays biodiversity points (blue), ecological factors (orange), and biosphere reserve zones (green) within a single interactive map.
- GIS Drawing Tools: Built-in editor for drawing conservation areas or habitat polygons directly on the map.
- Advanced Popups: Rich detail popups featuring image carousels, embedded YouTube videos, and anti-phishing link cards.

#### 2. Analytical Dashboard

- Real-time data visualization using Chart.js (Distribution Status & Top Countries).
- Paginated data tables with instant search.
- Automatically generated KPI (Key Performance Indicator) statistics.

#### 3. Security & Data Integrity

- Contributor Mode (Login): CRUD features are restricted to authenticated users.
- Input Validation: Basic HTML sanitization and URL validation to prevent XSS.
- Lock Service: Prevents data conflicts during concurrent backend operations.

#### 4. Data Interoperability

- CSV Export: Download complete datasets for analysis.
- DCMI Export: Supports Dublin Core metadata standard.

### Installation & Setup

#### Step 1: Prepare Google Sheets

Create three sheets:

**Nodes (Biodiversity Data)**  
Headers:
ID, Local Name, Latin Name, Country, Lat, Lng, AffectedBy Local Name, AffectedBy Latin Name, AffectedBy Country, AffectedBy Lat, AffectedBy Lng, Connection Type, Contact, Geometry JSON, Youtube URL, UNESCO Status, Research Links, Image URL, Description

**Biosphere (Biosphere Reserve Data)**  
Headers:
ID, Name Bio, Country, Region, UNESCO Year, Status, Area Total Ha, Youtube URL, Geometry JSON, Research Links, Image URL, Description

**Users (Authentication)**  
Headers:
Username, Password

#### Step 2: Deploy Backend (Google Apps Script)

Extensions → Apps Script  
Copy backend.gs → Deploy → Web App

Configuration:
- Execute as: Me
- Who has access: Anyone

#### Step 3: Configure Frontend

Edit:

const GAS_URL = 'https://script.google.com/macros/s/AKfycb.../exec';

### Tech Stack

Frontend: HTML5, Tailwind CSS, Leaflet.js, Chart.js  
Backend: Google Apps Script  
Database: Google Sheets

### Security Notes

- Anti-XSS protection
- Anti-phishing external links
- LockService concurrency protection


## Google Apps Script Backend (Data API)

Copy and paste the following script into your Google Apps Script project.

```javascript
/**
 * KONFIGURASI NAMA SHEET
 * Pastikan nama tab di Google Sheet Anda PERSIS sama dengan ini (huruf kecil semua sesuai screenshot Anda).
 */
const CONFIG = {
  NODES: "nodes",
  USERS: "users",
  BIOSPHERE: "biosphere"
};

function doGet(e) {
  return handleResponse();
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    return responseJSON({ status: 'error', message: 'Server busy, try again.' });
  }

  try {
    const action = e.parameter.action;
    const ss = SpreadsheetApp.getActiveSpreadsheet();

    if (action === 'login') {
      const user = e.parameter.username;
      const pass = e.parameter.password;
      if (user === 'adminJohnSmith' && pass === 'admin123WeberManJhensen') {
         return responseJSON({ status: 'success', message: 'Login Valid' });
      } else {
         return responseJSON({ status: 'error', message: 'Invalid Credentials' });
      }
    }

    if (action === 'delete') {
      const type = e.parameter.type;
      const id = e.parameter.id;
      const sheetName = (type === 'biosphere') ? CONFIG.BIOSPHERE : CONFIG.NODES;
      const sheet = ss.getSheetByName(sheetName);
      if (!sheet) throw new Error("Sheet not found: " + sheetName);

      const result = deleteRow(sheet, id);
      return responseJSON(result);
    }

    if (action === 'update' || action === 'insert') {
      const type = e.parameter.type;
      const rawData = e.parameter.data;

      if (!rawData) throw new Error("No data provided");
      const dataObj = JSON.parse(rawData);

      const sheetName = (type === 'biosphere') ? CONFIG.BIOSPHERE : CONFIG.NODES;
      const sheet = ss.getSheetByName(sheetName);
      if (!sheet) throw new Error("Sheet not found: " + sheetName);

      const uniqueKey = (type === 'biosphere') ? 'name_bio' : null;
      const prefix = (type === 'biosphere') ? 'BIO' : 'NODE';

      const result = upsertRow(sheet, dataObj, prefix, uniqueKey, sheetName);
      return responseJSON(result);
    }

    return responseJSON({ status: 'error', message: 'Unknown Action: ' + action });

  } catch (err) {
    return responseJSON({ status: 'error', message: err.toString() });
  } finally {
    lock.releaseLock();
  }
}
```

