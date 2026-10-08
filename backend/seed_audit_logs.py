#!/usr/bin/env python3
"""Seed script to populate audit_logs table with sample data."""

import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone
import random

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db, DB_PATH

# Sample data generators
def generate_timestamp(days_ago=0, hours_ago=0, minutes_ago=0):
    """Generate a timestamp in ISO format."""
    now = datetime.now(timezone.utc)
    delta = timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)
    return (now - delta).isoformat()

def generate_sample_data():
    """Generate sample audit log events."""
    actors = ['admin1', 'admin2', 'System', 'Bot', 'Automation']
    actions = ['login', 'logout', 'message_sent', 'message_received', 'campaign_started', 
              'campaign_stopped', 'handover_toggled', 'settings_updated', 'system_event']
    categories = ['Authentication', 'Messaging', 'Campaigns', 'System', 'Users']
    statuses = ['success', 'failed', 'pending']
    
    sample_description_templates = [
        "{} logged in from IP {}",
        "{} sent message to {} recipient(s)", 
        "{} received message from user {}",
        "{} started campaign '{}'",
        "{} stopped campaign '{}'",
        "{} toggled handover to {}",
        "{} updated {} settings",
        "System event: {}",
        "User {} was created by {}",
        "User {} was updated by {}"
    ]
    
    IP_addresses = ['192.168.1.1', '192.168.1.2', '192.168.1.3', '10.0.0.1', '10.0.0.2']
    user_names = ['john_doe', 'jane_smith', 'bob_wilson', 'alice_brown', 'charlie_davis']
    campaign_names = ['Summer Sale', 'Winter Collection', 'New Arrivals', 'Flash Sale', 'Holiday Special']
    settings_types = ['theme', 'notifications', 'permissions', 'profile', 'security']
    
    events = []
    
    # Generate 100 sample events over the last 30 days
    for i in range(100):
        days_ago = random.randint(0, 30)
        hours_ago = random.randint(0, 23)
        minutes_ago = random.randint(0, 59)
        
        timestamp = generate_timestamp(days_ago, hours_ago, minutes_ago)
        actor = random.choice(actors)
        action = random.choice(actions)
        category = random.choice(categories)
        status = random.choice(statuses)
        
        # Generate description
        template_idx = random.randint(0, len(sample_description_templates) - 1)
        template = sample_description_templates[template_idx]
        
        # Fill template based on action
        if action == 'login':
            description = template.format(actor, random.choice(IP_addresses))
        elif action == 'logout':
            description = template.format(actor)
        elif action == 'message_sent':
            description = template.format(actor, random.randint(1, 100))
        elif action == 'message_received':
            description = template.format(actor, random.choice(user_names))
        elif action == 'campaign_started':
            description = template.format(actor, random.choice(campaign_names))
        elif action == 'campaign_stopped':
            description = template.format(actor, random.choice(campaign_names))
        elif action == 'handover_toggled':
            toggled_to = random.choice(['ON', 'OFF'])
            description = template.format(actor, toggled_to)
        elif action == 'settings_updated':
            description = template.format(actor, random.choice(settings_types))
        else:
            description = template.format('System', f'Daily cleanup {i}')
        
        # Add some failed events
        if status == 'failed' and action not in ['login', 'logout']:
            description += " - Failed due to invalid input"
        
        metadata = {
            "ip_address": random.choice(IP_addresses) if action in ['login', 'logout'] else None,
            "user_agent": f"Mozilla/5.0 (Browser v{random.randint(1, 100)})" if action in ['login', 'message_sent'] else None,
            "entity_id": str(random.randint(1, 1000)),
            "additional_info": f"Sample metadata for event {i}"
        }
        
        # Remove None values
        metadata = {k: v for k, v in metadata.items() if v is not None}
        
        events.append({
            'created_at': timestamp,
            'actor': actor,
            'action': action,
            'category': category,
            'status': status,
            'description': description,
            'metadata': str(metadata).replace("'", "''")
        })
    
    return events

def seed_audit_logs():
    """Seed the audit_logs table with sample data."""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_logs'")
        if not cursor.fetchone():
            print("Error: audit_logs table does not exist. Run migration first.")
            return False
        
        # Clear existing data
        cursor.execute("DELETE FROM audit_logs")
        print(f"Cleared existing data from audit_logs")
        
        # Get sample data
        events = generate_sample_data()
        
        # Insert sample data
        insert_query = """
            INSERT INTO audit_logs 
            (created_at, actor, action, category, status, description, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        
        cursor.executemany(insert_query, [(
            event['created_at'],
            event['actor'],
            event['action'],
            event['category'],
            event['status'],
            event['description'],
            event['metadata']
        ) for event in events])
        
        conn.commit()
        print(f"Successfully inserted {len(events)} sample audit log events")
        return True
        
    except Exception as e:
        print(f"Error seeding audit_logs: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def main():
    print("🌱 Seeding audit_logs table with Healthy Earth sample data...")
    success = seed_audit_logs()
    if success:
        print("✅ Seeding completed successfully!")
    else:
        print("❌ Seeding failed")
    return success

if __name__ == "__main__":
    main()