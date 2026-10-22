#!/usr/bin/env python3
"""
Cleanup script for past events.

Deletes all events with event_date < today from the database.
Optionally vacuums the SQLite database to reclaim disk space.

Usage:
    python scripts/cleanup_past_events.py [--vacuum] [--dry-run]

Options:
    --vacuum   Run VACUUM after deletion to reclaim disk space
    --dry-run  Show what would be deleted without actually deleting
"""

import os
import sys
import sqlite3


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Get a database connection without trying to create directories."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def count_past_events(conn: sqlite3.Connection) -> int:
    """Count events with dates in the past."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM events
        WHERE event_date < date('now')
    """)
    return cursor.fetchone()[0]


def get_past_events(conn: sqlite3.Connection) -> list:
    """Get all past events for display."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, event_date, event_name, venue
        FROM events
        WHERE event_date < date('now')
        ORDER BY event_date ASC
    """)
    return cursor.fetchall()


def delete_past_events(conn: sqlite3.Connection) -> int:
    """Delete all events with dates in the past."""
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM events
        WHERE event_date < date('now')
    """)
    conn.commit()
    return cursor.rowcount


def vacuum_database(conn: sqlite3.Connection) -> None:
    """Run VACUUM to reclaim disk space."""
    cursor = conn.cursor()
    cursor.execute("VACUUM")
    conn.commit()
    print("Database vacuumed successfully.")


def main():
    """Main entry point."""
    # Parse arguments
    do_vacuum = "--vacuum" in sys.argv
    dry_run = "--dry-run" in sys.argv

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)

    # Default to the project-local data directory
    db_path = os.path.join(project_dir, "data", "events.db")

    print(f"Connecting to database: {db_path}")
    conn = get_db_connection(db_path)

    try:
        # Count and show past events
        past_count = count_past_events(conn)

        if past_count == 0:
            print("No past events found. Nothing to clean up.")
            return

        print(f"\nFound {past_count} past event(s):")
        print("-" * 60)

        for event in get_past_events(conn):
            event_id, event_date, event_name, venue = event
            print(f"  {event_date}: {event_name} ({venue})")

        print("-" * 60)

        if dry_run:
            print("\n[DRY RUN] No changes made.")
            print(f"Would delete {past_count} event(s).")
            return

        # Confirm deletion
        if len(sys.argv) == 1:
            # Interactive mode - ask for confirmation
            response = input(f"\nDelete {past_count} past event(s)? [y/N]: ")
            if response.lower() != 'y':
                print("Cancelled.")
                return

        # Delete past events
        deleted = delete_past_events(conn)
        print(f"\nDeleted {deleted} event(s).")

        # Optional vacuum
        if do_vacuum:
            vacuum_database(conn)

        # Show remaining count
        remaining = count_past_events(conn)
        print(f"\nRemaining past events: {remaining}")

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
