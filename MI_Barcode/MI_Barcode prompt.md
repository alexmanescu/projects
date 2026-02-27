Prompt for Claude Code:

I need you to set up a PHP/MySQL web application for a Barcode Generation and Printing utility called MI_Barcode. This tool will connect to an existing database to look up items by UPC and generate printable PDF labels tailored for both multi-label sheets and single-label thermal printers.

Phase 1 scope (what we're building now):

Read-only database connection to an existing MySQL database (alexmane_upc_audit) for UPC lookups.

A user interface to search for items by UPC, view item details, and select a label printing profile.

A database schema (or local storage mechanism) for saving "Label Profiles" (e.g., 4x6 thermal, Avery 30-up sheet, etc.) defining inches wide/high and layout.

PDF generation utility (using a robust library like TCPDF or FPDF) to create properly scaled, printable labels.

Barcode generation incorporating specific formatting: utilizing UPC-A, Code 128, or standard Code 39 formats, specifically wrapping the UPC strings in asterisks (e.g., *764083XXXXXX*) to ensure they scan correctly on our devices.

Dynamic layout placing the company's MI logo (PNG format), the barcode, and specific item fields (description, UOM, and the SKU/Part/Model number) onto the configured label canvas.

Technical stack:

PHP 8+ with PDO for database access.

MySQL for data storage (connecting to the existing alexmane_upc_audit DB, plus creating a local table for label configurations).

A PHP PDF library (like TCPDF, which natively supports barcodes and precise inch-based layout, eliminating the strict need for external web fonts).

Vanilla HTML/CSS/JavaScript (no frontend frameworks — keep it lightweight and fast).

Single config.php file for all database credentials and settings (must be git-ignored).

Database schema requirements:

Existing Database (alexmane_upc_audit): You will need to query the existing table holding the item data. Assume the table has fields similar to: upc, description, uom, part_number, model_number, sku. (Write the queries to prioritize sku, fallback to part_number, fallback to model_number depending on what is populated).

New Table (can be in a new DB or appended to an existing one for settings) label_profiles: id, profile_name, label_width_inches, label_height_inches, labels_per_row, labels_per_column, margin_top, margin_left, horizontal_spacing, vertical_spacing.

Label/PDF requirements:

Must scale the MI logo (logo.png) to fit cleanly at the top or side of each label without distortion.

Include the following text fields clearly: Description, Unit of Measure (UOM), and the Part Number / Model Number / SKU (whichever is available).

The barcode must be easily scannable. Format the data string with wrapped asterisks (*UPC*) as required by the scanners.

Support for two primary modes:

Thermal Mode: Continuous feed, one label per PDF page, exact dimensions (e.g., 2"x1" or 4"x6").

Sheet Mode: Standard 8.5"x11" paper outputting multiple labels per page based on rows/columns and spacing metrics.

Security & Architecture requirements:

All database queries must use prepared statements (PDO).

Input sanitization on all search inputs to prevent SQL injection.

Graceful error handling if a UPC is not found in alexmane_upc_audit.

File structure:
/MI_Barcode
/config
config.php (git-ignored, contains DB credentials for the audit DB)
config.example.php (template for config.php)
/includes
db.php (database connection)
pdf_generator.php (wrapper for the PDF/Barcode library)
functions.php (utility functions for data fallback logic)
/public
index.php (UPC search interface and item preview)
print.php (endpoint that generates and outputs the PDF)
profiles.php (CRUD for managing label sizes/layouts)
/assets
/css
style.css (clean, desktop-friendly layout since printing is usually from a PC)
/js
app.js (vanilla JS for form handling and preview updates)
/img
logo.png (placeholder for the MI logo)
/lib
(Composer vendor folder or downloaded PDF library files like TCPDF)
/sql
schema.sql (schema for the label_profiles table)
.gitignore
README.md

Initial features needed:

Search Page: A simple, large input field focused on fast UPC entry (or scanner input).

Result View: Shows the queried item data, alerts if missing, and provides a dropdown to select the "Print Profile" (e.g., Zebra Thermal, Avery 5160). Include a quantity input for how many labels to print.

PDF Output: Clicking "Print" generates the PDF in a new browser tab, automatically formatted to the dimensions of the selected profile, with the logo, text, and asterisk-wrapped barcode.

Profile Manager: A simple settings page to add/edit/delete label configurations (width, height, rows, columns).

UI/UX priorities:

Clean, high-contrast, desktop-optimized interface (printing context).

Auto-focus the search bar on page load so a user can just scan a barcode to initiate a search.

Clear error states (e.g., "UPC not found in audit database").

Git setup:

Initialize git repo.

Create .gitignore that excludes config/config.php, vendor/ or lib/ (if using composer), and standard temp files.

First commit should include the complete structure, schema, PDF logic, and a working lookup/print flow.

README should include:

Brief project description.

Setup instructions (how to configure DB connections, especially connecting to the existing alexmane_upc_audit).

Instructions on replacing the placeholder assets/img/logo.png with the actual MI logo.

Details on how the asterisk-wrapped barcode generation works.

Create the entire project structure, write all the code (including the necessary PDF/barcode library integration), set up git, and make the first commit. Ensure clear comments explaining the PDF dimension math and the fallback logic for SKU/Part Number.