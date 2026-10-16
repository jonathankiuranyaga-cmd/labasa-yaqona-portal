"""Create the database and deterministic demonstration accounts/data."""
import os
from werkzeug.security import generate_password_hash
from app import app, init_db

with app.app_context():
    init_db()
    db = app.extensions.get("database")
    # Use the app's database connection via Flask request context.
    from flask import g
    import sqlite3
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    users = [
        ("Portal Administrator", "admin@yaqona.local", "AdminDemo123!", "admin", "00000000", "Labasa", "Labasa Yaqona Portal", "System administrator", "approved"),
        ("Adi Mere Vula", "farmer@yaqona.local", "FarmerDemo123!", "farmer", "9991001", "Labasa", "", "Family yaqona farm near Labasa.", "approved"),
        ("Jone Ratu", "farmer2@yaqona.local", "FarmerDemo123!", "farmer", "9991002", "Savusavu", "Ratu Farm", "Smallholder grower in Cakaudrove.", "approved"),
        ("Vanua Levu Buyer", "buyer@yaqona.local", "BuyerDemo123!", "buyer", "9992001", "Labasa", "Island Produce Co.", "Buying for local wholesale.", "approved"),
        ("Pacific Kava Exports", "exporter@yaqona.local", "ExportDemo123!", "exporter", "9993001", "Savusavu", "Pacific Kava Exports", "Export buyer; subject to applicable standards.", "approved"),
        ("Pending Farmer Example", "pending@yaqona.local", "PendingDemo123!", "farmer", "9991003", "Seaqaqa", "", "Demo pending account.", "pending"),
    ]
    ids = {}
    for name,email,password,role,phone,location,business,bio,status in users:
        row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if row:
            ids[email] = row["id"]
            continue
        cur = conn.execute("""INSERT INTO users (name,email,password_hash,role,phone,location,business_name,bio,status)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (name,email,generate_password_hash(password),role,phone,location,business,bio,status))
        ids[email] = cur.lastrowid
    samples = [
        (ids["farmer@yaqona.local"], "Waka", 120, "kg", "Fully dried", "Labasa", 48.00, "Clean, fully dried waka. Sample listing for demonstration.", "approved"),
        (ids["farmer@yaqona.local"], "Lewena", 65, "kg", "Partly dried", "Labasa", 28.00, "Lewena available; final terms to be agreed directly.", "approved"),
        (ids["farmer2@yaqona.local"], "Waka", 200, "kg", "Fully dried", "Savusavu", 52.00, "Sample waka listing from Cakaudrove.", "approved"),
        (ids["farmer2@yaqona.local"], "Mixed", 40, "bags", "Fresh", "Savusavu", 18.00, "Fresh mixed yaqona. Demonstration data only.", "pending"),
    ]
    for farmer,kt,qty,unit,drying,loc,price,desc,status in samples:
        exists = conn.execute("SELECT id FROM listings WHERE farmer_id=? AND kava_type=? AND description=?", (farmer,kt,desc)).fetchone()
        if not exists:
            conn.execute("""INSERT INTO listings (farmer_id,kava_type,quantity,unit,drying_status,location,price,description,status)
                VALUES (?,?,?,?,?,?,?,?,?)""", (farmer,kt,qty,unit,drying,loc,price,desc,status))
    prices = [
        ("Waka","2026-07",50.00,"Sample indicative price; not a guaranteed market quote."),
        ("Lewena","2026-07",30.00,"Sample indicative price; confirm current terms with counterparties."),
        ("Waka","2026-08",51.50,"Demonstration data only."),
        ("Lewena","2026-08",29.00,"Demonstration data only."),
        ("Waka","2026-09",52.00,"Demonstration data only."),
        ("Lewena","2026-09",31.00,"Demonstration data only."),
        ("Mixed","2026-09",22.00,"Demonstration data only."),
    ]
    for kt,month,price,note in prices:
        conn.execute("INSERT OR IGNORE INTO price_guide (kava_type,month,price_per_kg,notes,created_by) VALUES (?,?,?,?,?)",
            (kt,month,price,note,ids["admin@yaqona.local"]))
    # Seed a sample conversation if it doesn't already exist.
    listing = conn.execute("SELECT id,farmer_id FROM listings WHERE status='approved' ORDER BY id LIMIT 1").fetchone()
    buyer_id = ids["buyer@yaqona.local"]
    if listing:
        cur = conn.execute("SELECT id FROM enquiries WHERE listing_id=? AND buyer_id=?", (listing["id"],buyer_id)).fetchone()
        if not cur:
            ecur = conn.execute("INSERT INTO enquiries (listing_id,buyer_id,farmer_id) VALUES (?,?,?)",
                (listing["id"],buyer_id,listing["farmer_id"]))
            conn.execute("INSERT INTO messages (enquiry_id,sender_id,body) VALUES (?,?,?)",
                (ecur.lastrowid,buyer_id,"Bula, is this listing still available? Please share any collection details."))
    conn.commit()
    conn.close()
    print("Database initialised and sample data inserted.")
    print("Demo logins:")
    print("Admin:    admin@yaqona.local / AdminDemo123!")
    print("Farmer:   farmer@yaqona.local / FarmerDemo123!")
    print("Buyer:    buyer@yaqona.local / BuyerDemo123!")
    print("Exporter: exporter@yaqona.local / ExportDemo123!")
    print("Pending:  pending@yaqona.local / PendingDemo123!")
