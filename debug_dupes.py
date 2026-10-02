import sqlite3
import json

db_path = "/app/data/telegram_cache.db"
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Search for the specific news story
    cursor.execute("SELECT id, source, date, text FROM posts WHERE text LIKE '%Трамп%Европу%пожирают%'")
    rows = cursor.fetchall()
    
    print(f"Found {len(rows)} matches:")
    for row in rows:
        print(f"ID: {row[0]} | Source: {row[1]} | Date: {row[2]} | Text: {row[3][:100]}...")
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
