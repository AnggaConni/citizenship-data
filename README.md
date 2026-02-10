# 🌍 Global Biodiversity & Biosphere 2026 (BioSphere)

BioSphere adalah Aplikasi Web GIS (Geographic Information System) progresif untuk memvisualisasikan, memantau, dan mengelola data keanekaragaman hayati (Biodiversity) dan Cagar Biosfer (Biosphere Reserves). Aplikasi ini dibangun dengan pendekatan serverless menggunakan Google Sheets sebagai database.

✨ Fitur Utama

1. 🗺️ Peta Interaktif (GIS)

Multi-Layer Visualization: Menampilkan titik biodiversitas (biru), faktor ekologis (oranye), dan zona cagar biosfer (hijau) dalam satu peta.

GIS Drawing Tool: Editor bawaan untuk menggambar poligon area konservasi atau habitat langsung di atas peta.

Advanced Popups: Popup detail dengan carousel gambar, video YouTube, dan "Kartu Link" anti-phishing.

2. 📊 Dashboard Analitik

Visualisasi data real-time dengan Chart.js (Status Distribusi & Top Countries).

Tabel data dengan paginasi dan pencarian instan.

Statistik KPI (Key Performance Indicators) otomatis.

3. 🛡️ Keamanan & Integritas Data

Mode Kontributor (Login): Proteksi fitur CRUD (Create, Read, Update, Delete) hanya untuk pengguna terdaftar.

Validasi Input: Sanitasi HTML dasar dan validasi URL untuk mencegah XSS.

Lock Service: Mencegah konflik data saat penyimpanan bersamaan di backend.

4. 📤 Interoperabilitas Data

Export CSV: Unduh dataset lengkap untuk analisis di Excel/SPSS.

Export DCMI: Dukungan standar metadata Dublin Core untuk integrasi perpustakaan digital.

🛠️ Instalasi & Setup

Langkah 1: Persiapan Google Sheet (Database)

Buat Spreadsheet baru di Google Drive, dan buat 3 Sheet (Tab) dengan nama persis berikut:

Nodes (Untuk Data Biodiversitas)

Header Baris 1: ID, Local Name, Latin Name, Country, Lat, Lng, AffectedBy Local Name, AffectedBy Latin Name, AffectedBy Country, AffectedBy Lat, AffectedBy Lng, Connection Type, Contact, Geometry JSON, Youtube URL, UNESCO Status, Research Links, Image URL, Description

Biosphere (Untuk Data Cagar Biosfer)

Header Baris 1: ID, Name Bio, Country, Region, UNESCO Year, Status, Area Total Ha, Youtube URL, Geometry JSON, Research Links, Image URL, Description

Users (Untuk Login)

Header Baris 1: Username, Password

Isi Data: Masukkan username dan password admin di baris ke-2 dst.

Langkah 2: Deploy Backend (Google Apps Script)

Di Google Sheet, klik menu Extensions > Apps Script.

Hapus kode yang ada, lalu Copy-Paste kode dari file backend.gs (tersedia di bawah).

Klik tombol Deploy > New Deployment.

Pilih type: Web App.

Konfigurasi:

Description: v1

Execute as: Me (Email Anda).

Who has access: Anyone (Penting agar frontend bisa akses).

Klik Deploy dan salin Web App URL.

Langkah 3: Konfigurasi Frontend

Buka file index.html.

Cari variabel const GAS_URL (biasanya di bagian bawah script).

Ganti URL di dalamnya dengan Web App URL yang Anda dapatkan di Langkah 2.

const GAS_URL = '[https://script.google.com/macros/s/AKfycb.../exec](https://script.google.com/macros/s/AKfycb.../exec)'; 


💻 Tech Stack

Frontend: HTML5, Tailwind CSS (CDN), Leaflet.js (Maps), Chart.js (Stats), FontAwesome.

Backend: Google Apps Script (Node.js environment).

Database: Google Sheets.

📝 Catatan Audit Keamanan

Aplikasi ini telah diaudit untuk keamanan tingkat dasar hingga menengah:

✅ Anti-XSS: Input deskripsi dibersihkan dari tag script berbahaya.

✅ Anti-Phishing: Link eksternal ditampilkan dengan domain jelas dan menggunakan atribut rel="noopener noreferrer".

✅ Concurrency: Backend menggunakan LockService untuk menangani antrian request.
