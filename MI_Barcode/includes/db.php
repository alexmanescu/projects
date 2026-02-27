<?php
/**
 * MI_Barcode — Database connections
 *
 * getAuditDb()    — read connection to alexmane_upc_audit (UPC lookups)
 * getProfilesDb() — connection for the label_profiles table (CRUD)
 *
 * Both connections use PDO with ERRMODE_EXCEPTION and FETCH_ASSOC defaults.
 * If both point to the same host/db/user, getProfilesDb() reuses the
 * same PDO instance to avoid redundant connections.
 */

declare(strict_types=1);

function getAuditDb(): PDO
{
    static $db = null;
    if ($db === null) {
        $dsn = 'mysql:host=' . AUDIT_DB_HOST
             . ';dbname=' . AUDIT_DB_NAME
             . ';charset=utf8mb4';
        $db = new PDO($dsn, AUDIT_DB_USER, AUDIT_DB_PASS, [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ]);
    }
    return $db;
}

function getProfilesDb(): PDO
{
    static $db = null;
    if ($db === null) {
        // Reuse the audit connection if it targets the same database.
        if (
            PROFILES_DB_HOST === AUDIT_DB_HOST &&
            PROFILES_DB_NAME === AUDIT_DB_NAME &&
            PROFILES_DB_USER === AUDIT_DB_USER
        ) {
            return getAuditDb();
        }

        $dsn = 'mysql:host=' . PROFILES_DB_HOST
             . ';dbname=' . PROFILES_DB_NAME
             . ';charset=utf8mb4';
        $db = new PDO($dsn, PROFILES_DB_USER, PROFILES_DB_PASS, [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ]);
    }
    return $db;
}
