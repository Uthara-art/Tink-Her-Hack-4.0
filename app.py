from flask import Flask, render_template, request, redirect
import os
import uuid
import sqlite3
from datetime import datetime

app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ---------------- DATABASE INIT ----------------

def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            location TEXT,
            type TEXT,
            contact TEXT,
            image TEXT,
            status TEXT,
            date TEXT,
            claimant TEXT,
            claim_details TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- HOME ----------------

@app.route('/')
def home():
    return render_template('index.html')

# ---------------- ADD ITEM ----------------

@app.route('/add', methods=['GET', 'POST'])
def add_item():

    if request.method == 'POST':

        name = request.form['name']
        description = request.form['description']
        location = request.form['location']
        item_type = request.form['type']
        contact = request.form['contact']

        image = request.files['image']
        filename = ""

        if image and image.filename != "":
            filename = image.filename
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        conn = sqlite3.connect("database.db")
        c = conn.cursor()

        c.execute("""
            INSERT INTO items
            (id, name, description, location, type, contact, image, status, date, claimant, claim_details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            name,
            description,
            location,
            item_type,
            contact,
            filename,
            "Open",
            datetime.now().strftime("%d %b %Y, %I:%M %p"),
            None,
            None
        ))

        conn.commit()
        conn.close()

        return redirect('/view')

    return render_template('add_item.html')

# ---------------- VIEW ITEMS ----------------

@app.route('/view')
def view_items():

    search = request.args.get('search')
    filter_type = request.args.get('type')
    filter_status = request.args.get('status')

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    query = "SELECT * FROM items WHERE 1=1"
    params = []

    if search:
        query += " AND LOWER(name) LIKE ?"
        params.append(f"%{search.lower()}%")

    if filter_type:
        query += " AND type=?"
        params.append(filter_type)

    if filter_status:
        query += " AND status=?"
        params.append(filter_status)

    c.execute(query, params)
    items = c.fetchall()

    # ---------- BEST MULTI-FACTOR MATCHING ----------

    def word_overlap(text1, text2):
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())

        if len(set1) == 0:
            return 0

        return len(set1.intersection(set2)) / len(set1)

    matches = {}

    lost_list = [item for item in items if item['type'].lower() == 'lost' and item['status'].lower() == 'open']
    found_list = [item for item in items if item['type'].lower() == 'found' and item['status'].lower() == 'open']

    for lost in lost_list:

        best_score = 0
        best_found = None

        for found in found_list:

            name_score = word_overlap(lost['name'], found['name'])
            desc_score = word_overlap(lost['description'], found['description'])
            location_score = 1 if lost['location'].lower() == found['location'].lower() else 0

            final_score = (0.5 * name_score) + (0.3 * desc_score) + (0.2 * location_score)

            if final_score > best_score:
                best_score = final_score
                best_found = found

        if best_score > 0.5:
            matches[lost['id']] = {
                "found_id": best_found['id'],
                "score": round(best_score * 100, 2)
            }

    # ---------- Dashboard counts ----------

    c.execute("SELECT COUNT(*) FROM items")
    total = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM items WHERE status='Open'")
    open_items = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM items WHERE status='Resolved'")
    resolved_items = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM items WHERE type='Lost'")
    lost_items = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM items WHERE type='Found'")
    found_items = c.fetchone()[0]

    recovery_rate = round((resolved_items / total) * 100, 2) if total > 0 else 0

    conn.close()

    return render_template(
        'view_items.html',
        items=items,
        total=total,
        open_items=open_items,
        resolved_items=resolved_items,
        lost_items=lost_items,
        found_items=found_items,
        recovery_rate=recovery_rate,
        matches=matches
    )

# ---------------- CLAIM ----------------

@app.route('/claim/<id>', methods=['GET', 'POST'])
def claim_item(id):

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == 'POST':

        claimant_name = request.form['name']
        claimant_contact = request.form['contact']
        proof = request.form['proof']

        claim_details = f"Contact: {claimant_contact} | Proof: {proof}"

        c.execute("""
            UPDATE items
            SET status='Claim Requested',
                claimant=?,
                claim_details=?
            WHERE id=?
        """, (claimant_name, claim_details, id))

        conn.commit()
        conn.close()

        return redirect('/view')

    c.execute("SELECT * FROM items WHERE id=?", (id,))
    item = c.fetchone()
    conn.close()

    return render_template("claim.html", item=item)

# ---------------- APPROVE ----------------

@app.route('/approve/<id>')
def approve_claim(id):

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
        UPDATE items
        SET status='Resolved'
        WHERE id=?
    """, (id,))

    conn.commit()
    conn.close()

    return redirect('/view')
# ---------------- VIEW BEST MATCH ----------------

@app.route('/match/<lost_id>')
def view_best_match(lost_id):

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get lost item
    c.execute("SELECT * FROM items WHERE id=?", (lost_id,))
    lost_item = c.fetchone()

    if not lost_item:
        conn.close()
        return "Lost item not found"

    # Get all open found items
    c.execute("SELECT * FROM items WHERE type='Found' AND status='Open'")
    found_items = c.fetchall()

    def word_overlap(text1, text2):
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())
        if len(set1) == 0:
            return 0
        return len(set1.intersection(set2)) / len(set1)

    best_score = 0
    best_found = None

    for found in found_items:

        name_score = word_overlap(lost_item['name'], found['name'])
        desc_score = word_overlap(lost_item['description'], found['description'])
        location_score = 1 if lost_item['location'].lower() == found['location'].lower() else 0

        final_score = (0.5 * name_score) + (0.3 * desc_score) + (0.2 * location_score)

        if final_score > best_score:
            best_score = final_score
            best_found = found

    conn.close()

    return render_template(
        "best_match.html",
        lost=lost_item,
        found=best_found,
        score=round(best_score * 100, 2)
    )

# ---------------- RUN ----------------

if __name__ == '__main__':
    app.run(debug=True)
