import os
import csv
import sqlite3
from ftplib import FTP
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_FILE = "books.db"

def sync_ftp_data():
    ftp_host = os.environ.get("FTP_HOST")
    ftp_user = os.environ.get("FTP_USER")
    ftp_pass = os.environ.get("FTP_PASS")
    remote_filename = os.environ.get("FTP_FILENAME", "books.csv")
    local_filename = "downloaded_books.csv"

    if not ftp_host or not ftp_user or not ftp_pass:
        print("FTP credentials not fully configured.")
        return

    try:
        ftp = FTP(ftp_host)
        ftp.login(user=ftp_user, passwd=ftp_pass)
        with open(local_filename, "wb") as f:
            ftp.retrbinary(f"RETR {remote_filename}", f.write)
        ftp.quit()

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Drop the old table and create the new expanded one
        cursor.execute("DROP TABLE IF EXISTS books")
        cursor.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                primary_author TEXT,
                title TEXT,
                isbn TEXT,
                format TEXT,
                price TEXT,
                bisac TEXT,
                imprint TEXT,
                publisher TEXT,
                publish_date TEXT,
                allow_presales TEXT
            )
        """)

        with open(local_filename, mode="r", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            to_db = []
            for row in reader:
                # Using .get() with alternatives covers you if Excel capitalizes a header
                to_db.append((
                    row.get("primary_author") or row.get("Primary_Author") or "",
                    row.get("title") or row.get("Title") or "",
                    row.get("isbn") or row.get("ISBN") or "",
                    row.get("format") or row.get("Format") or "",
                    row.get("price") or row.get("Price") or "",
                    row.get("bisac") or row.get("BISAC") or "",
                    row.get("imprint") or row.get("Imprint") or "",
                    row.get("publisher") or row.get("Publisher") or "",
                    row.get("publish_date") or row.get("Publish_Date") or "",
                    row.get("allow_presales") or row.get("Allow_Presales") or ""
                ))

            cursor.executemany("""
                INSERT INTO books (
                    primary_author, title, isbn, format, price, 
                    bisac, imprint, publisher, publish_date, allow_presales
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, to_db)

        # Add indexes for lightning-fast searching on all three main fields
        cursor.execute("CREATE INDEX idx_title ON books(title);")
        cursor.execute("CREATE INDEX idx_isbn ON books(isbn);")
        cursor.execute("CREATE INDEX idx_author ON books(primary_author);")

        conn.commit()
        conn.close()
        print("Database sync finished successfully!")
    except Exception as e:
        print(f"Error during FTP sync: {e}")

@app.route("/search", methods=["GET"])
def search_books():
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify([])

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # This allows us to return data as dictionaries easily
    cursor = conn.cursor()

    search_pattern = f"%{query}%"
    
    # Search across title, isbn, OR primary_author
    cursor.execute("""
        SELECT primary_author, title, isbn, format, price, bisac, imprint, publisher, publish_date, allow_presales
        FROM books 
        WHERE title LIKE ? OR isbn LIKE ? OR primary_author LIKE ?
        LIMIT 10
    """, (search_pattern, search_pattern, search_pattern))

    rows = cursor.fetchall()
    conn.close()

    results = [dict(row) for row in rows]
    return jsonify(results)

@app.route("/sync", methods=["GET"])
def trigger_sync():
    sync_ftp_data()
    return jsonify({"status": "Database sync complete"})

# Run sync automatically whenever Gunicorn loads the app
sync_ftp_data()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
