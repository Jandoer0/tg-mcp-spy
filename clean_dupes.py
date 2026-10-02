import sqlite3

db_path = "/app/data/telegram_cache.db"
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Находим группы дублей: один источник, один текст, но разные ID
    # Оставляем только самый старый (минимальный) ID из каждой группы
    cursor.execute("""
        DELETE FROM posts 
        WHERE id NOT IN (
            SELECT MIN(id) 
            FROM posts 
            GROUP BY source_id, text
        )
    """)
    
    deleted_count = cursor.rowcount
    conn.commit()
    print(f"Successfully deleted {deleted_count} duplicate posts.")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
