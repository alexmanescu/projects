-- ============================================================
-- AR Cleanup & Reconciliation Database
-- Mutual Industries - Sage 100 Post-Migration
-- ============================================================
-- Deploy: mysql -u root -p < schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS ar_cleanup
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE ar_cleanup;

-- ============================================================
-- REFERENCE TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS ecom_customers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  customer_code VARCHAR(20) NOT NULL UNIQUE,
  customer_name VARCHAR(100) NOT NULL,
  short_name VARCHAR(30) NOT NULL,
  portal_source VARCHAR(100) DEFAULT NULL COMMENT 'Where remit data comes from',
  edi_820_priority TINYINT DEFAULT 0 COMMENT '1=active, 2=planned, 0=none',
  search_priority INT DEFAULT 99,
  notes TEXT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS match_status_codes (
  code VARCHAR(20) PRIMARY KEY,
  label VARCHAR(50) NOT NULL,
  description VARCHAR(200) DEFAULT NULL,
  is_terminal TINYINT(1) DEFAULT 0 COMMENT '1=no further action needed'
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS import_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  import_type ENUM('open_invoices','remit_data','as400_xref','payment_history') NOT NULL,
  source_file VARCHAR(255) NOT NULL,
  customer_code VARCHAR(20) DEFAULT NULL,
  records_imported INT DEFAULT 0,
  records_skipped INT DEFAULT 0,
  records_errored INT DEFAULT 0,
  notes TEXT DEFAULT NULL,
  imported_by VARCHAR(50) DEFAULT NULL,
  imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ============================================================
-- CORE DATA TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS open_invoices (
  id INT AUTO_INCREMENT PRIMARY KEY,
  invoice_no VARCHAR(20) NOT NULL,
  division VARCHAR(5) DEFAULT NULL,
  customer_code VARCHAR(20) NOT NULL,
  customer_name VARCHAR(100) DEFAULT NULL,
  invoice_date DATE DEFAULT NULL,
  balance DECIMAL(12,2) NOT NULL DEFAULT 0,
  po_number VARCHAR(50) DEFAULT NULL,
  invoice_type VARCHAR(10) DEFAULT NULL COMMENT 'IN, CM, DM, PP',
  terms_code VARCHAR(10) DEFAULT NULL,
  is_as400 TINYINT(1) DEFAULT 0 COMMENT '1=AS400 legacy invoice',
  is_ecom TINYINT(1) DEFAULT 0,
  age_days INT DEFAULT NULL,
  age_bucket VARCHAR(20) DEFAULT NULL,
  audit_category VARCHAR(50) DEFAULT NULL COMMENT 'From original audit workbook categorization',
  resolution_status VARCHAR(20) DEFAULT 'open' COMMENT 'open, matched, partial_match, written_off, pending_review',
  resolution_notes TEXT DEFAULT NULL,
  snapshot_date DATE NOT NULL COMMENT 'Date of the S.I. export this came from',
  import_batch_id INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  
  INDEX idx_invoice_no (invoice_no),
  INDEX idx_customer (customer_code),
  INDEX idx_balance (balance),
  INDEX idx_status (resolution_status),
  INDEX idx_ecom (is_ecom),
  INDEX idx_as400 (is_as400),
  INDEX idx_age_bucket (age_bucket),
  INDEX idx_snapshot (snapshot_date),
  UNIQUE KEY uk_invoice_snapshot (invoice_no, division, snapshot_date)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS remit_records (
  id INT AUTO_INCREMENT PRIMARY KEY,
  customer_code VARCHAR(20) NOT NULL,
  customer_name VARCHAR(100) DEFAULT NULL,
  invoice_no VARCHAR(50) DEFAULT NULL COMMENT 'Invoice # as it appears in the remit file',
  invoice_no_normalized VARCHAR(20) DEFAULT NULL COMMENT 'Cleaned/padded to match Sage format',
  po_number VARCHAR(50) DEFAULT NULL,
  payment_amount DECIMAL(12,2) DEFAULT NULL,
  discount_amount DECIMAL(12,2) DEFAULT 0,
  net_payment DECIMAL(12,2) DEFAULT NULL COMMENT 'payment_amount - discount_amount',
  check_number VARCHAR(50) DEFAULT NULL,
  remit_reference VARCHAR(100) DEFAULT NULL COMMENT 'EFT ref, ACH trace, wire ref, etc.',
  payment_date DATE DEFAULT NULL,
  remit_date DATE DEFAULT NULL COMMENT 'Date on the remit advice if different from payment',
  deduction_code VARCHAR(50) DEFAULT NULL COMMENT 'Chargeback/deduction reason codes',
  deduction_description VARCHAR(200) DEFAULT NULL,
  source_file VARCHAR(255) NOT NULL,
  source_row INT DEFAULT NULL COMMENT 'Row number in source file for traceability',
  source_format VARCHAR(20) DEFAULT NULL COMMENT 'csv, xlsx, pdf_extracted',
  import_batch_id INT DEFAULT NULL,
  is_matched TINYINT(1) DEFAULT 0,
  match_id INT DEFAULT NULL COMMENT 'FK to match_results if matched',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  
  INDEX idx_customer (customer_code),
  INDEX idx_invoice (invoice_no_normalized),
  INDEX idx_payment_date (payment_date),
  INDEX idx_check (check_number),
  INDEX idx_matched (is_matched),
  INDEX idx_source (source_file),
  INDEX idx_import_batch (import_batch_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS match_results (
  id INT AUTO_INCREMENT PRIMARY KEY,
  open_invoice_id INT NOT NULL,
  remit_record_id INT DEFAULT NULL COMMENT 'NULL for write-off matches',
  customer_code VARCHAR(20) NOT NULL,
  invoice_no VARCHAR(20) NOT NULL,
  
  -- Match details
  match_type VARCHAR(20) NOT NULL COMMENT 'exact, partial, amount_only, cross_customer, cross_customer_dup, manual, write_off',
  match_confidence DECIMAL(5,2) DEFAULT NULL COMMENT '0-100 score',
  
  -- Financial details
  invoice_balance DECIMAL(12,2) NOT NULL,
  remit_amount DECIMAL(12,2) DEFAULT NULL,
  remit_discount DECIMAL(12,2) DEFAULT 0,
  variance DECIMAL(12,2) DEFAULT NULL COMMENT 'balance - (remit_amount + discount)',
  
  -- Resolution
  status VARCHAR(20) DEFAULT 'pending' COMMENT 'pending, approved, rejected, exported, posted',
  resolution_action VARCHAR(30) DEFAULT NULL COMMENT 'cash_receipt, debit_memo, credit_memo, write_off, journal_entry',
  gl_account VARCHAR(20) DEFAULT NULL COMMENT 'Target GL account for the correction',
  batch_name VARCHAR(30) DEFAULT NULL COMMENT 'VI batch name when exported',
  
  -- Audit
  matched_by VARCHAR(20) DEFAULT 'system' COMMENT 'system or username',
  reviewed_by VARCHAR(50) DEFAULT NULL,
  reviewed_at TIMESTAMP NULL DEFAULT NULL,
  exported_at TIMESTAMP NULL DEFAULT NULL,
  posted_at TIMESTAMP NULL DEFAULT NULL,
  notes TEXT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  
  INDEX idx_invoice (open_invoice_id),
  INDEX idx_remit (remit_record_id),
  INDEX idx_customer (customer_code),
  INDEX idx_status (status),
  INDEX idx_type (match_type),
  INDEX idx_action (resolution_action),
  INDEX idx_batch (batch_name),
  FOREIGN KEY (open_invoice_id) REFERENCES open_invoices(id),
  FOREIGN KEY (remit_record_id) REFERENCES remit_records(id)
) ENGINE=InnoDB;

-- Audit trail for status changes
CREATE TABLE IF NOT EXISTS match_audit_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  match_id INT NOT NULL,
  field_changed VARCHAR(50) NOT NULL,
  old_value VARCHAR(200) DEFAULT NULL,
  new_value VARCHAR(200) DEFAULT NULL,
  changed_by VARCHAR(50) DEFAULT NULL,
  changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  
  INDEX idx_match (match_id),
  FOREIGN KEY (match_id) REFERENCES match_results(id)
) ENGINE=InnoDB;

-- VI export batches
CREATE TABLE IF NOT EXISTS vi_export_batches (
  id INT AUTO_INCREMENT PRIMARY KEY,
  batch_name VARCHAR(30) NOT NULL UNIQUE,
  batch_type ENUM('cash_receipt','debit_memo','credit_memo') NOT NULL,
  customer_code VARCHAR(20) DEFAULT NULL COMMENT 'NULL for multi-customer batches',
  record_count INT DEFAULT 0,
  total_amount DECIMAL(14,2) DEFAULT 0,
  gl_account VARCHAR(20) DEFAULT NULL,
  status ENUM('staged','exported','imported_test','posted_test','imported_prod','posted_prod') DEFAULT 'staged',
  export_file VARCHAR(255) DEFAULT NULL,
  notes TEXT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  
  INDEX idx_status (status),
  INDEX idx_type (batch_type)
) ENGINE=InnoDB;

-- ============================================================
-- REFERENCE DATA INSERTS
-- ============================================================

INSERT INTO ecom_customers (customer_code, customer_name, short_name, portal_source, edi_820_priority, search_priority) VALUES
('46004300', 'Orgill Inc', 'Orgill', 'Orgill vendor portal', 0, 1),
('42625300', 'Homedepot.Com #8119', 'HD.com', 'RetailLink / True Commerce', 2, 2),
('40256500', 'Amazon.Com Dedc,Llc', 'Amazon DC', 'Amazon Vendor Central', 0, 3),
('43800000', 'The Home Depot', 'HD B&M', 'RetailLink / True Commerce', 0, 4),
('40257500', 'Amazon.Com', 'Amazon DS', 'Amazon Vendor Central', 0, 5),
('48432100', 'Lowe''s Companies Inc', 'Lowes', 'Lowe''s vendor portal', 0, 6),
('40730200', 'Tractor Supply Co', 'TSC', 'TSC vendor portal', 1, 7),
('42900300', 'Zoro', 'Zoro', 'Zoro vendor portal', 0, 8),
('48096900', 'Staples Advantage', 'Staples Adv', 'Staples portal / True Commerce', 0, 9),
('48096800', 'Staples Exchange', 'Staples Exch', 'Staples portal / True Commerce', 0, 10),
('46842200', 'Quill Corporation', 'Quill', 'Quill portal (Staples sub)', 0, 11),
('42315600', 'Do It Best Corp 7730', 'DIB', 'Do It Best portal', 0, 12),
('49200300', 'White Cap HDS Const Supply #6025', 'White Cap', 'White Cap vendor portal', 0, 13),
('44657200', 'Grainger/Accounts Payable Dept', 'Grainger', 'Grainger vendor portal', 0, 14),
('47634300', 'T V Hardware Distribution, LLC', 'TV Hardware', 'True Value portal', 0, 15),
('40199000', 'ACE Hardware', 'ACE', 'ACE Hardware portal', 0, 16)
ON DUPLICATE KEY UPDATE customer_name=VALUES(customer_name);

INSERT INTO match_status_codes (code, label, description, is_terminal) VALUES
('pending', 'Pending Review', 'Match identified by system, awaiting human review', 0),
('approved', 'Approved', 'Match reviewed and approved for VI export', 0),
('rejected', 'Rejected', 'Match reviewed and rejected - needs different resolution', 0),
('exported', 'Exported to VI', 'Approved match exported to VI import sheet', 0),
('imported_test', 'Imported to Test', 'VI sheet imported to copy/test company', 0),
('posted_test', 'Posted in Test', 'Batch posted and verified in test company', 0),
('imported_prod', 'Imported to Prod', 'VI sheet imported to production company', 0),
('posted_prod', 'Posted in Prod', 'Batch posted in production - COMPLETE', 1),
('write_off', 'Written Off', 'Approved for bad debt write-off', 1),
('manual', 'Manual Resolution', 'Flagged for manual processing outside this system', 1)
ON DUPLICATE KEY UPDATE label=VALUES(label);

-- ============================================================
-- VIEWS
-- ============================================================

CREATE OR REPLACE VIEW v_dashboard_summary AS
SELECT 
  oi.customer_code,
  ec.short_name,
  COUNT(*) as total_invoices,
  SUM(CASE WHEN oi.balance > 0 THEN 1 ELSE 0 END) as positive_count,
  SUM(CASE WHEN oi.balance < 0 THEN 1 ELSE 0 END) as negative_count,
  SUM(CASE WHEN oi.balance > 0 THEN oi.balance ELSE 0 END) as positive_total,
  SUM(CASE WHEN oi.balance < 0 THEN oi.balance ELSE 0 END) as negative_total,
  SUM(oi.balance) as net_balance,
  SUM(oi.is_as400) as as400_count,
  SUM(CASE WHEN oi.resolution_status = 'open' THEN 1 ELSE 0 END) as open_count,
  SUM(CASE WHEN oi.resolution_status = 'matched' THEN 1 ELSE 0 END) as matched_count,
  SUM(CASE WHEN ABS(oi.balance) <= 20 THEN 1 ELSE 0 END) as under_20_count
FROM open_invoices oi
LEFT JOIN ecom_customers ec ON oi.customer_code = ec.customer_code
WHERE oi.is_ecom = 1
GROUP BY oi.customer_code, ec.short_name
ORDER BY SUM(oi.balance) DESC;

CREATE OR REPLACE VIEW v_remit_coverage AS
SELECT 
  rr.customer_code,
  ec.short_name,
  COUNT(DISTINCT rr.source_file) as file_count,
  COUNT(*) as total_records,
  MIN(rr.payment_date) as earliest_payment,
  MAX(rr.payment_date) as latest_payment,
  SUM(rr.payment_amount) as total_payments,
  SUM(CASE WHEN rr.is_matched = 1 THEN 1 ELSE 0 END) as matched_records,
  SUM(CASE WHEN rr.is_matched = 0 THEN 1 ELSE 0 END) as unmatched_records
FROM remit_records rr
LEFT JOIN ecom_customers ec ON rr.customer_code = ec.customer_code
GROUP BY rr.customer_code, ec.short_name;

CREATE OR REPLACE VIEW v_match_pipeline AS
SELECT 
  mr.status,
  ms.label as status_label,
  mr.resolution_action,
  COUNT(*) as record_count,
  SUM(mr.invoice_balance) as total_balance,
  SUM(mr.remit_amount) as total_remit,
  SUM(mr.variance) as total_variance
FROM match_results mr
LEFT JOIN match_status_codes ms ON mr.status = ms.code
GROUP BY mr.status, ms.label, mr.resolution_action;

CREATE OR REPLACE VIEW v_unmatched_invoices AS
SELECT 
  oi.*,
  ec.short_name
FROM open_invoices oi
LEFT JOIN ecom_customers ec ON oi.customer_code = ec.customer_code
WHERE oi.resolution_status = 'open'
  AND oi.is_ecom = 1
ORDER BY ABS(oi.balance) DESC;
