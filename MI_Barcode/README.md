# MI Barcode

A PHP/MySQL web utility for looking up items by UPC and printing formatted labels on thermal printers and sheet label stock.

---

## Setup

### 1. Install dependencies
```bash
composer install
```

### 2. Configure database
```bash
cp config/config.example.php config/config.php
```

Edit `config/config.php` and fill in your credentials:

- **AUDIT_DB_\*** — connection to the existing `alexmane_upc_audit` database (read-only for UPC lookups).
- **AUDIT_TABLE** — the table name in that database holding item records. Expected columns: `upc`, `description`, `uom`, `part_number`, `model_number`, `sku`.
- **PROFILES_DB_\*** — connection for the `label_profiles` table. This can point to the same database as the audit DB.

### 3. Run the schema
Run `sql/schema.sql` against the database configured as `PROFILES_DB_NAME`:
```bash
mysql -u your_user -p alexmane_upc_audit < sql/schema.sql
```
This creates the `label_profiles` table and seeds it with common label formats (Zebra thermal, Avery sheets).

### 4. Add your MI logo
Place the MI logo at:
```
assets/img/logo.png
```
The PDF generator scales it proportionally to fit the top of each label. Without this file, labels are generated without a logo.

---

## Usage

### Lookup & Print (`public/index.php`)
- The UPC input is auto-focused on load — scan a barcode or type a UPC and press Enter.
- On a successful lookup, item details appear along with a profile selector and quantity input.
- Click **Print Labels** to generate a PDF in a new browser tab.

### Label Profiles (`public/profiles.php`)
- Create and manage label size configurations.
- **Thermal mode**: set `Labels per Row = 1` and `Labels per Column = 1`. Each label becomes its own PDF page sized to the label dimensions.
- **Sheet mode**: set rows/columns > 1. Labels are laid out on 8.5" × 11" pages using the margin and spacing values.

---

## Barcode format

The default barcode type is **Code 39** (`C39`).

Code 39 uses `*` as start/stop delimiters — the barcode encodes `*{UPC}*`. TCPDF adds these automatically when using the `C39` format, so the data string is passed plain (e.g. `764083XXXXXX`). The rendered barcode will scan as `*764083XXXXXX*` on your scanners.

To switch to Code 128 (more compact), change `DEFAULT_BARCODE_FORMAT` to `'C128'` in `config/config.php`.

---

## Part number fallback logic

When printing labels, the identifier shown under description follows this priority:

1. **SKU** — if populated
2. **part_number** — fallback
3. **model_number** — second fallback
4. `N/A` — if all three are empty

---

## File structure

```
MI_Barcode/
├── config/
│   ├── config.php          (git-ignored — your local credentials)
│   └── config.example.php  (template)
├── includes/
│   ├── db.php              (PDO singleton helpers)
│   ├── functions.php       (UPC lookup, part# fallback, profile CRUD)
│   └── pdf_generator.php   (TCPDF label layout engine)
├── public/
│   ├── index.php           (UPC search + print form)
│   ├── print.php           (PDF generation endpoint)
│   └── profiles.php        (Label profile CRUD)
├── assets/
│   ├── css/style.css
│   ├── js/app.js
│   └── img/logo.png        (place MI logo here)
├── sql/
│   └── schema.sql          (label_profiles DDL + seed data)
├── vendor/                 (Composer — git-ignored)
├── composer.json
└── .gitignore
```
