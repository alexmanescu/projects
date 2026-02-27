# MI Order Fulfillment Manager (MI_OFM)

Phase 1 of a multi-phase warehouse order tracking system that replaces a paper-based workflow. Built with PHP 8+, MySQL, and vanilla HTML/CSS/JS.

## Setup

### Requirements
- PHP 8.0+
- MySQL 5.7+ or MariaDB 10.3+
- Web server (Apache/Nginx) with PHP

### 1. Database

```sql
mysql -u root -p -e "CREATE DATABASE mi_ofm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p mi_ofm < sql/schema.sql
mysql -u root -p mi_ofm < sql/seed.sql
```

### 2. Configuration

```bash
cp config/config.example.php config/config.php
```

Edit `config/config.php` with your database credentials. This file is git-ignored.

### 3. Create admin user

Visit `http://yourserver/MI_OFM/public/setup.php` in a browser, or run:

```bash
php public/setup.php
```

**Delete `public/setup.php` immediately after running it.**

Default credentials created by setup:

| Username       | Password    | Role       | Dept   |
|----------------|-------------|------------|--------|
| admin          | Admin@1234  | Admin      | —      |
| supervisor1    | Supervisor@1| Supervisor | —      |
| puller_inside1 | Puller@1234 | Puller     | Inside |
| puller_inside2 | Puller@1234 | Puller     | Inside |
| puller_yard1   | Puller@1234 | Puller     | Yard   |

**Change all passwords after first login.**

### 4. Web server

Point your document root to `/MI_OFM/` (or configure a virtual host). The login page is at `public/index.php`.

---

## Usage

### Roles

**Admin**
- All supervisor capabilities
- Create/edit/deactivate users
- Create/edit orders manually (until Sage integration)

**Supervisor**
- Dashboard: all orders with current assignments
- Manually assign orders to pullers
- Release orders back to the queue
- View audit log per order
- Visual urgency flags for approaching ship dates

**Puller**
- Personal queue: available orders + active assignments
- Claim available orders
- Update status: Assigned → In Progress → Staged → Ready for Dock → Complete
- Update pulled quantities on order lines

### Order Status Flow

```
New → Assigned → In Progress → Staged → Ready for Dock → Completed
```

Color codes: Gray=New, Blue=Assigned, Amber=In Progress, Green=Staged, Purple=Ready for Dock, Dark=Completed

### Urgency Indicators

Orders are highlighted by days until required ship date:
- **Overdue** — past ship date (red)
- **Critical** — ships today/tomorrow (red)
- **High** — ships in ≤3 days (amber)
- **Medium** — ships in ≤7 days (blue)

---

## File Structure

```
MI_OFM/
  config/
    config.example.php    Template — copy to config.php
    config.php            Local credentials (git-ignored)
  includes/
    db.php                PDO database connection
    auth.php              Session, CSRF, login/logout helpers
    functions.php         Shared utilities (audit log, status helpers, etc.)
    header.php            Shared HTML header + nav
    footer.php            Shared HTML footer
  public/
    index.php             Login page
    dashboard.php         Supervisor/admin order dashboard
    puller_queue.php      Puller's personal order queue
    order_detail.php      Single order view with line items
    admin_orders.php      Admin: create/edit orders
    admin_users.php       Admin: user management
    api.php               AJAX endpoint (status updates, claims)
    logout.php            Session destruction
    setup.php             One-time admin user creation (delete after use)
  assets/
    css/style.css         Mobile-first responsive stylesheet
    js/app.js             Minimal vanilla JS
  sql/
    schema.sql            Full database schema
    seed.sql              Sample data (stages, locations, orders)
  .gitignore
  README.md
```

---

## Roadmap

- **Phase 2** — Sage 100 integration (auto-import orders, item codes, customer data)
- **Phase 3** — Barcode scanning support (AJAX scan-to-pull on mobile)
- **Phase 4** — Reporting dashboard (throughput, on-time rate, puller performance)
- **Phase 5** — Real-time push updates via WebSocket or SSE

---

## Security Notes

- All database queries use PDO prepared statements
- CSRF token validated on every POST
- Sessions: httponly, SameSite=Strict, idle timeout (8 hours)
- Passwords: bcrypt, cost 12, minimum 8 characters
- Input sanitized with `htmlspecialchars` before output
- `config.php` is git-ignored and must never be committed
