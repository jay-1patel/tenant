#!/usr/bin/env python3
"""Migration script to add IP address and user agent columns to admin_audit_events table."""

import sqlite3
import os
import sys

# Add the backend directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db, BASE_DIR, PROJECT_ROOT, DB_PATH

def migrate():
    """Add IP address and user agent columns to existing admin_audit_events table."""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(admin_audit_events)")
        columns = [row[1] for row in cursor.fetchall()]
        
        print(f"Current columns: {columns}")
        
        # Add IP address column if it doesn't exist
        if "ip_address" not in columns:
            cursor.execute("ALTER TABLE admin_audit_events ADD COLUMN ip_address TEXT")
            print("Added ip_address column")
        else:
            print("ip_address column already exists")
        
        # Add user agent column if it doesn't exist
        if "user_agent" not in columns:
            cursor.execute("ALTER TABLE admin_audit_events ADD COLUMN user_agent TEXT")
            print("Added user_agent column")
        else:
            print("user_agent column already exists")
        
        conn.commit()
        print("Migration completed successfully")
        
    except Exception as e:
        print(f"Migration failed: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()
    
    return True

if __name__ == "__main__":
    print("Running migration to add IP and user agent to audit events...")
    success = migrate()
    if success:
        print("✅ Migration completed")
        sys.exit(0)
    else:
        print("❌ Migration failed")
        sys.exit(1)