import os
import csv
import sqlite3
from ftplib import FTP
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
# Enable CORS so Qualtrics can talk to this API
CORS(app)

DB_FILE = "books.db"

def sync_ftp_data():
    """Logs into FTP, downloads the CSV file, and updates SQLite database."""
    ftp_host = os.environ.get("FTP_HOST")
    ftp_user = os.environ.get("FTP_USER")
    ftp_pass = os.environ.get("FTP_PASS")
    remote_filename = os.environ.get("FTP_FILENAME", "books.csv")
    local_filename = "downloaded_books.csv"

    if not ftp_host or not ftp_user or not ftp_pass:
        print("FTP credentials not fully configured in environment variables.")
        return

    try:
        print("Connecting to FTP server...")
        ftp = FTP(ftp_host)
        ftp.login(user=ftp_user, passwd=ftp_pass)
        
        with open(local_filename, "wb") as f:
            ftp.retrbinary(f"RETR {remote_filename}", f.write)
        ftp.quit()
        print("FTP download successful.")

        # Rebuild SQLite database
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute("DROP TABLE IF EXISTS books")
        cursor.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                isbn TEXT
            )
        """)

        # Parse CSV file into SQLite
        with open(local_filename, mode="r", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            to_db = []
            for row in reader:
                # Flexible lookup for CSV headers named Title/title/ISBN/isbn
                title = row.get("Title") or row.get("title") or ""
                isbn = row.get("ISBN") or row.get("isbn") or ""
                to_db.append((title, isbn))

            cursor.executemany("INSERT INTO books (title, isbn) VALUES (?, ?);", to_db)

        # Create search indexes so lookups run instantly
        cursor.execute("CREATE INDEX idx_title ON books(title);")
        cursor.execute("CREATE INDEX idx_isbn ON books(isbn);")

        conn.commit()
        conn.close()
        print("Database sync finished successfully!")
    except Exception as e:
        print(f"Error during FTP sync: {e}")

# Search API endpoint used by Qualtrics
@app.route("/search", methods=["GET"])
def search_books():
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify([])

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    search_pattern = f"%{query}%"
    cursor.execute("""
        SELECT title, isbn 
        FROM books 
        WHERE title LIKE ? OR isbn LIKE ? 
        LIMIT 10
    """, (search_pattern, search_pattern))

    rows = cursor.fetchall()
    conn.close()

    results = [{"title": row[0], "isbn": row[1]} for row in rows]
    return jsonify(results)

# Webhook route to trigger a re-sync on demand
@app.route("/sync", methods=["GET"])
def trigger_sync():
    sync_ftp_data()
    return jsonify({"status": "Database sync complete"})

if __name__ == "__main__":
    sync_ftp_data()
    app.run(host="0.0.0.0", port=5000)