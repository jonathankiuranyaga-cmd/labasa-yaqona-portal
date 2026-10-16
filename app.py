import os
import re
import sqlite3
import uuid
from functools import wraps
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort, send_from_directory
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from config import Config, ALLOWED_IMAGE_EXTENSIONS, allowed_image

app = Flask(__name__)
app.config.from_object(Config)
app.permanent_session_lifetime = timedelta(hours=8)
csrf = CSRFProtect(app)


def ensure_upload_dir():
    upload_folder = app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)


# Ensure upload directory exists when the app is imported.
ensure_upload_dir()

ROLES = {"farmer", "buyer", "exporter"}
LOCATIONS = [
    "Labasa", "Savusavu", "Seaqaqa", "Nabouwalu", "Dreketi", "Wainikoro",
    "Cakaudrove", "Bua", "Macuata", "Other Vanua Levu"
]
KAVA_TYPES = ["Waka", "Lewena", "Mixed", "Other"]
DRYING = ["Fresh", "Partly dried", "Fully dried"]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, encoding="utf-8") as schema:
        db.executescript(schema.read())
    db.commit()
    db.close()


@app.before_request
def load_user():
    g.user = None
    uid = session.get("user_id")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if g.user is None or g.user["status"] != "approved":
            session.clear()
            g.user = None


_schema_migrated = False


@app.before_request
def ensure_schema():
    global _schema_migrated
    if not _schema_migrated:
        get_db().execute("""CREATE TABLE IF NOT EXISTS listing_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        get_db().execute("CREATE INDEX IF NOT EXISTS idx_listing_images_listing ON listing_images(listing_id, sort_order)")
        get_db().commit()
        _schema_migrated = True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login"))
            if g.user["role"] not in roles:
                abort(403)
            if g.user["status"] != "approved":
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(view):
    return roles_required("admin")(view)


def clean_text(value, max_len=500):
    value = (value or "").strip()
    return value[:max_len]


def valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You do not have permission to view this page."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We could not find that page."), 404


@app.errorhandler(413)
def too_large(_error):
    flash("That form was too large. Please shorten the text and try again.", "error")
    return redirect(request.referrer or url_for("index"))


@app.route("/")
def index():
    db = get_db()
    listings = db.execute("""SELECT l.*, u.name AS farmer_name FROM listings l
        JOIN users u ON u.id=l.farmer_id
        WHERE l.status='approved' AND u.status='approved'
        ORDER BY l.created_at DESC LIMIT 3""").fetchall()
    return render_template("index.html", listings=listings)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = clean_text(request.form.get("name"), 100)
        email = clean_text(request.form.get("email"), 160).lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        phone = clean_text(request.form.get("phone"), 40)
        location = clean_text(request.form.get("location"), 100)
        business_name = clean_text(request.form.get("business_name"), 120)
        if not name or not valid_email(email) or len(password) < 8 or role not in ROLES or not location:
            flash("Check your details. Use a valid email, choose an account type and location, and use a password of at least 8 characters.", "error")
            return render_template("auth/register.html", locations=LOCATIONS)
        try:
            get_db().execute("""INSERT INTO users
                (name,email,password_hash,role,phone,location,business_name,status)
                VALUES (?,?,?,?,?,?,?,'pending')""",
                (name, email, generate_password_hash(password), role, phone, location, business_name))
            get_db().commit()
        except sqlite3.IntegrityError:
            flash("An account with that email already exists. Please log in or use another email.", "error")
            return render_template("auth/register.html", locations=LOCATIONS)
        flash("Registration received. An administrator must approve your account before you can log in.", "success")
        return redirect(url_for("login"))
    return render_template("auth/register.html", locations=LOCATIONS)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = clean_text(request.form.get("email"), 160).lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
        elif user["status"] == "pending":
            flash("Your account is awaiting administrator approval.", "error")
        elif user["status"] in ("rejected", "deactivated"):
            flash("This account is not active. Contact the portal administrator.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            flash("Welcome back.", "success")
            return redirect(url_for("dashboard"))
    return render_template("auth/login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    role = g.user["role"]
    if role == "admin":
        return redirect(url_for("admin_dashboard"))
    if role == "farmer":
        return redirect(url_for("farmer_dashboard"))
    return redirect(url_for("buyer_dashboard"))


@app.route("/dashboard/farmer")
@roles_required("farmer")
def farmer_dashboard():
    db = get_db()
    listings = db.execute("SELECT * FROM listings WHERE farmer_id=? AND status!='removed' ORDER BY created_at DESC", (g.user["id"],)).fetchall()
    enquiries = db.execute("""SELECT e.*, l.kava_type, l.location, u.name AS other_name,
        (SELECT body FROM messages m WHERE m.enquiry_id=e.id ORDER BY m.id DESC LIMIT 1) AS last_message
        FROM enquiries e JOIN listings l ON l.id=e.listing_id
        JOIN users u ON u.id=e.buyer_id WHERE e.farmer_id=? ORDER BY e.updated_at DESC""", (g.user["id"],)).fetchall()
    return render_template("dashboards/farmer.html", listings=listings, enquiries=enquiries)


@app.route("/dashboard/buyer")
@roles_required("buyer", "exporter")
def buyer_dashboard():
    enquiries = get_db().execute("""SELECT e.*, l.kava_type, l.location, u.name AS farmer_name,
        (SELECT body FROM messages m WHERE m.enquiry_id=e.id ORDER BY m.id DESC LIMIT 1) AS last_message
        FROM enquiries e JOIN listings l ON l.id=e.listing_id
        JOIN users u ON u.id=e.farmer_id WHERE e.buyer_id=? ORDER BY e.updated_at DESC""", (g.user["id"],)).fetchall()
    return render_template("dashboards/buyer.html", enquiries=enquiries)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = clean_text(request.form.get("name"), 100)
        phone = clean_text(request.form.get("phone"), 40)
        location = clean_text(request.form.get("location"), 100)
        business_name = clean_text(request.form.get("business_name"), 120)
        bio = clean_text(request.form.get("bio"), 600)
        if not name or not location:
            flash("Name and location are required.", "error")
        else:
            get_db().execute("""UPDATE users SET name=?,phone=?,location=?,business_name=?,bio=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (name, phone, location, business_name, bio, g.user["id"]))
            get_db().commit()
            flash("Your profile has been updated.", "success")
            return redirect(url_for("profile"))
    return render_template("profile.html", locations=LOCATIONS)


@app.route("/listings")
def browse_listings():
    db = get_db()
    keyword = clean_text(request.args.get("q"), 100)
    location = clean_text(request.args.get("location"), 100)
    kava_type = clean_text(request.args.get("kava_type"), 50)
    drying = clean_text(request.args.get("drying_status"), 30)
    min_price = request.args.get("min_price", "").strip()
    max_price = request.args.get("max_price", "").strip()
    page = max(1, min(int(request.args.get("page", 1) or 1), 100000))
    conditions = ["l.status='approved'", "u.status='approved'"]
    params = []
    if keyword:
        conditions.append("(l.kava_type LIKE ? OR l.location LIKE ? OR l.description LIKE ? OR u.name LIKE ?)")
        params.extend([f"%{keyword}%"] * 4)
    if location:
        conditions.append("l.location=?"); params.append(location)
    if kava_type:
        conditions.append("l.kava_type=?"); params.append(kava_type)
    if drying in DRYING:
        conditions.append("l.drying_status=?"); params.append(drying)
    try:
        if min_price:
            val = float(min_price)
            if val >= 0: conditions.append("l.price>=?"); params.append(val)
    except ValueError:
        flash("Minimum price must be a valid number.", "error")
    try:
        if max_price:
            val = float(max_price)
            if val >= 0: conditions.append("l.price<=?"); params.append(val)
    except ValueError:
        flash("Maximum price must be a valid number.", "error")
    where = " AND ".join(conditions)
    total = db.execute(f"SELECT COUNT(*) FROM listings l JOIN users u ON u.id=l.farmer_id WHERE {where}", params).fetchone()[0]
    per_page = 9
    listings = db.execute(f"""SELECT l.*, u.name AS farmer_name FROM listings l JOIN users u ON u.id=l.farmer_id
        WHERE {where} ORDER BY l.created_at DESC LIMIT ? OFFSET ?""", params + [per_page, (page-1)*per_page]).fetchall()
    listing_images = {}
    if listings:
        ids = [l["id"] for l in listings]
        placeholders = ",".join("?" * len(ids))
        rows = db.execute(f"""SELECT listing_id, filename FROM listing_images WHERE listing_id IN ({placeholders})
            ORDER BY sort_order ASC, id ASC""", ids).fetchall()
        for r in rows:
            listing_images.setdefault(r["listing_id"], []).append(r["filename"])
    return render_template("listings/browse.html", listings=listings, locations=LOCATIONS,
        kava_types=KAVA_TYPES, drying_options=DRYING, total=total, page=page,
        pages=max(1, (total+per_page-1)//per_page), listing_images=listing_images)


@app.route("/listings/<int:listing_id>")
def listing_detail(listing_id):
    listing = get_db().execute("""SELECT l.*, u.name AS farmer_name, u.location AS farmer_location,
        u.phone AS farmer_phone, u.business_name AS farmer_business, u.bio AS farmer_bio
        FROM listings l JOIN users u ON u.id=l.farmer_id
        WHERE l.id=? AND l.status='approved' AND u.status='approved'""", (listing_id,)).fetchone()
    if not listing:
        abort(404)
    images = get_db().execute("""SELECT * FROM listing_images WHERE listing_id=?
        ORDER BY sort_order ASC, id ASC""", (listing_id,)).fetchall()
    return render_template("listings/detail.html", listing=listing, images=images)


@app.route("/listings/new", methods=["GET", "POST"])
@roles_required("farmer")
def create_listing():
    if request.method == "POST":
        return save_listing(None)
    return render_template("listings/form.html", listing=None, kava_types=KAVA_TYPES, drying_options=DRYING)


@app.route("/listings/<int:listing_id>/edit", methods=["GET", "POST"])
@roles_required("farmer")
def edit_listing(listing_id):
    listing = get_db().execute("SELECT * FROM listings WHERE id=? AND farmer_id=? AND status!='removed'",
        (listing_id, g.user["id"])).fetchone()
    if not listing:
        abort(404)
    if request.method == "POST":
        return save_listing(listing_id)
    return render_template("listings/form.html", listing=listing, kava_types=KAVA_TYPES, drying_options=DRYING)


def save_listing(listing_id):
    kava_type = clean_text(request.form.get("kava_type"), 50)
    drying = clean_text(request.form.get("drying_status"), 30)
    location = clean_text(request.form.get("location"), 100)
    unit = request.form.get("unit", "kg")
    description = clean_text(request.form.get("description"), 1000)
    try:
        quantity = float(request.form.get("quantity", ""))
        price = float(request.form.get("price", ""))
    except ValueError:
        flash("Quantity and asking price must be numbers.", "error")
        return redirect(request.url)
    if kava_type not in KAVA_TYPES or drying not in DRYING or not location or quantity <= 0 or price < 0 or unit not in ("kg", "bags"):
        flash("Please check all fields. Quantity must be above zero and price cannot be negative.", "error")
        return redirect(request.url)
    db = get_db()
    listing_row_id = listing_id
    if listing_id:
        db.execute("""UPDATE listings SET kava_type=?,quantity=?,unit=?,drying_status=?,location=?,price=?,
            description=?,status='pending',admin_note='',updated_at=CURRENT_TIMESTAMP WHERE id=? AND farmer_id=?""",
            (kava_type, quantity, unit, drying, location, price, description, listing_id, g.user["id"]))
        message = "Your listing has been updated and sent for administrator review."
    else:
        cur = db.execute("""INSERT INTO listings (farmer_id,kava_type,quantity,unit,drying_status,location,price,description,status)
            VALUES (?,?,?,?,?,?,?,?, 'pending')""",
            (g.user["id"], kava_type, quantity, unit, drying, location, price, description))
        listing_row_id = cur.lastrowid
        message = "Your listing has been submitted for administrator review."

    # Handle image uploads.
    uploaded = request.files.getlist("images")
    saved = 0
    for file in uploaded:
        if not file or file.filename == "":
            continue
        if not allowed_image(file.filename):
            continue
        filename = secure_filename(file.filename)
        # Avoid collisions by prefixing with listing id, a short uuid and sequence.
        safe_name = f"{listing_row_id}_{uuid.uuid4().hex[:8]}_{saved}_{filename}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
        db.execute("""INSERT INTO listing_images (listing_id, filename, original_name, sort_order)
            VALUES (?,?,?,?)""", (listing_row_id, safe_name, file.filename, saved))
        saved += 1

    db.commit()
    flash(message, "success")
    return redirect(url_for("farmer_dashboard"))


@app.route("/listings/<int:listing_id>/deactivate", methods=["POST"])
@roles_required("farmer")
def deactivate_listing(listing_id):
    db = get_db()
    row = db.execute("SELECT id FROM listings WHERE id=? AND farmer_id=? AND status!='removed'", (listing_id, g.user["id"])).fetchone()
    if not row:
        abort(404)
    db.execute("UPDATE listings SET status='inactive',updated_at=CURRENT_TIMESTAMP WHERE id=?", (listing_id,))
    db.commit()
    flash("Listing deactivated. It is no longer visible to buyers.", "success")
    return redirect(url_for("farmer_dashboard"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/listings/<int:listing_id>/images", methods=["POST"])
@roles_required("farmer")
def upload_listing_image(listing_id):
    db = get_db()
    row = db.execute("SELECT id FROM listings WHERE id=? AND farmer_id=? AND status!='removed'",
                     (listing_id, g.user["id"])).fetchone()
    if not row:
        abort(404)
    uploaded = request.files.getlist("images")
    saved = 0
    max_sort = db.execute("SELECT COALESCE(MAX(sort_order), -1) FROM listing_images WHERE listing_id=?",
                          (listing_id,)).fetchone()[0]
    for file in uploaded:
        if not file or file.filename == "":
            continue
        if not allowed_image(file.filename):
            flash(f"Skipped {file.filename}: not a supported image type.", "error")
            continue
        filename = secure_filename(file.filename)
        safe_name = f"{listing_id}_{uuid.uuid4().hex[:8]}_{max_sort + saved + 1}_{filename}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
        db.execute("""INSERT INTO listing_images (listing_id, filename, original_name, sort_order)
            VALUES (?,?,?,?)""", (listing_id, safe_name, file.filename, max_sort + saved + 1))
        saved += 1
    db.commit()
    if saved:
        flash(f"{saved} image(s) uploaded.", "success")
    return redirect(url_for("listing_detail", listing_id=listing_id))


@app.route("/listings/<int:listing_id>/images/<int:image_id>/delete", methods=["POST"])
@roles_required("farmer")
def delete_listing_image(listing_id, image_id):
    db = get_db()
    image = db.execute("""SELECT i.* FROM listing_images i
        JOIN listings l ON l.id=i.listing_id
        WHERE i.id=? AND l.id=? AND l.farmer_id=? AND l.status!='removed'""",
        (image_id, listing_id, g.user["id"])).fetchone()
    if not image:
        abort(404)
    try:
        os.remove(os.path.join(app.config["UPLOAD_FOLDER"], image["filename"]))
    except OSError:
        pass
    db.execute("DELETE FROM listing_images WHERE id=?", (image_id,))
    db.commit()
    flash("Image deleted.", "success")
    return redirect(url_for("listing_detail", listing_id=listing_id))


@app.route("/listings/<int:listing_id>/enquire", methods=["POST"])
@roles_required("buyer", "exporter")
def send_enquiry(listing_id):
    db = get_db()
    listing = db.execute("SELECT * FROM listings WHERE id=? AND status='approved'", (listing_id,)).fetchone()
    if not listing:
        abort(404)
    body = clean_text(request.form.get("body"), 2000)
    if len(body) < 3:
        flash("Please write a short message before sending.", "error")
        return redirect(url_for("listing_detail", listing_id=listing_id))
    existing = db.execute("SELECT id FROM enquiries WHERE listing_id=? AND buyer_id=? AND farmer_id=?",
        (listing_id, g.user["id"], listing["farmer_id"])).fetchone()
    if existing:
        enquiry_id = existing["id"]
    else:
        cur = db.execute("INSERT INTO enquiries (listing_id,buyer_id,farmer_id) VALUES (?,?,?)",
            (listing_id, g.user["id"], listing["farmer_id"]))
        enquiry_id = cur.lastrowid
    db.execute("INSERT INTO messages (enquiry_id,sender_id,body) VALUES (?,?,?)", (enquiry_id, g.user["id"], body))
    db.execute("UPDATE enquiries SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (enquiry_id,))
    db.commit()
    flash("Enquiry sent. Payments are arranged separately between the parties.", "success")
    return redirect(url_for("conversation", enquiry_id=enquiry_id))


@app.route("/enquiries/<int:enquiry_id>", methods=["GET", "POST"])
@login_required
def conversation(enquiry_id):
    db = get_db()
    enquiry = db.execute("""SELECT e.*, l.kava_type, l.location, l.status AS listing_status,
        b.name AS buyer_name, f.name AS farmer_name FROM enquiries e
        JOIN listings l ON l.id=e.listing_id JOIN users b ON b.id=e.buyer_id
        JOIN users f ON f.id=e.farmer_id WHERE e.id=?""", (enquiry_id,)).fetchone()
    if not enquiry:
        abort(404)
    if g.user["role"] != "admin" and g.user["id"] not in (enquiry["buyer_id"], enquiry["farmer_id"]):
        abort(403)
    if request.method == "POST":
        body = clean_text(request.form.get("body"), 2000)
        if len(body) < 1:
            flash("Please write a reply first.", "error")
        else:
            db.execute("INSERT INTO messages (enquiry_id,sender_id,body) VALUES (?,?,?)", (enquiry_id, g.user["id"], body))
            db.execute("UPDATE enquiries SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (enquiry_id,))
            db.commit()
            flash("Reply sent.", "success")
            return redirect(url_for("conversation", enquiry_id=enquiry_id))
    messages = db.execute("""SELECT m.*, u.name AS sender_name, u.role AS sender_role FROM messages m
        JOIN users u ON u.id=m.sender_id WHERE m.enquiry_id=? ORDER BY m.id""", (enquiry_id,)).fetchall()
    return render_template("enquiries/conversation.html", enquiry=enquiry, messages=messages)


@app.route("/price-guide")
def price_guide():
    rows = get_db().execute("SELECT * FROM price_guide ORDER BY month DESC, kava_type").fetchall()
    chart_rows = get_db().execute("""SELECT month, AVG(price_per_kg) AS average_price
        FROM price_guide GROUP BY month ORDER BY month""").fetchall()
    return render_template("price_guide.html", rows=rows, chart_rows=chart_rows)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    counts = {
        "pending_users": db.execute("SELECT COUNT(*) FROM users WHERE status='pending' AND role!='admin'").fetchone()[0],
        "pending_listings": db.execute("SELECT COUNT(*) FROM listings WHERE status='pending'").fetchone()[0],
        "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "listings": db.execute("SELECT COUNT(*) FROM listings WHERE status!='removed'").fetchone()[0],
    }
    users = db.execute("SELECT * FROM users WHERE role!='admin' ORDER BY created_at DESC LIMIT 100").fetchall()
    listings = db.execute("""SELECT l.*,u.name AS farmer_name FROM listings l JOIN users u ON u.id=l.farmer_id
        WHERE l.status!='removed' ORDER BY l.created_at DESC LIMIT 100""").fetchall()
    prices = db.execute("SELECT * FROM price_guide ORDER BY month DESC LIMIT 100").fetchall()
    search = clean_text(request.args.get("q"), 100)
    if search:
        users = db.execute("""SELECT * FROM users WHERE role!='admin' AND (name LIKE ? OR email LIKE ? OR location LIKE ?)
            ORDER BY created_at DESC LIMIT 100""", (f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
        listings = db.execute("""SELECT l.*,u.name AS farmer_name FROM listings l JOIN users u ON u.id=l.farmer_id
            WHERE l.status!='removed' AND (l.kava_type LIKE ? OR l.location LIKE ? OR u.name LIKE ?)
            ORDER BY l.created_at DESC LIMIT 100""", (f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
    return render_template("admin/dashboard.html", counts=counts, users=users, listings=listings, prices=prices, search=search)


@app.route("/admin/users/<int:user_id>/status", methods=["POST"])
@admin_required
def admin_user_status(user_id):
    status = request.form.get("status")
    note = clean_text(request.form.get("admin_note"), 300)
    if status not in ("approved", "rejected", "deactivated", "pending"):
        abort(400)
    if user_id == g.user["id"]:
        flash("You cannot change your own administrator account status here.", "error")
        return redirect(url_for("admin_dashboard"))
    db = get_db()
    row = db.execute("SELECT id,role FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or row["role"] == "admin":
        abort(404)
    db.execute("UPDATE users SET status=?,admin_note=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, note, user_id))
    db.commit()
    flash("Account status updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/listings/<int:listing_id>/status", methods=["POST"])
@admin_required
def admin_listing_status(listing_id):
    status = request.form.get("status")
    note = clean_text(request.form.get("admin_note"), 300)
    if status not in ("approved", "rejected", "inactive", "removed", "pending"):
        abort(400)
    db = get_db()
    row = db.execute("SELECT id FROM listings WHERE id=?", (listing_id,)).fetchone()
    if not row:
        abort(404)
    db.execute("UPDATE listings SET status=?,admin_note=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, note, listing_id))
    db.commit()
    flash("Listing status updated. The farmer can see any review note on their dashboard.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/prices/add", methods=["POST"])
@admin_required
def admin_add_price():
    kava_type = clean_text(request.form.get("kava_type"), 50)
    month = clean_text(request.form.get("month"), 7)
    notes = clean_text(request.form.get("notes"), 300)
    try:
        price = float(request.form.get("price_per_kg", ""))
    except ValueError:
        flash("Price must be a valid number.", "error")
        return redirect(url_for("admin_dashboard"))
    if not kava_type or not re.fullmatch(r"\d{4}-\d{2}", month) or price < 0:
        flash("Enter a kava type, a month in YYYY-MM format, and a non-negative price.", "error")
        return redirect(url_for("admin_dashboard"))
    try:
        get_db().execute("""INSERT INTO price_guide (kava_type,month,price_per_kg,notes,created_by)
            VALUES (?,?,?,?,?)""", (kava_type, month, price, notes, g.user["id"]))
        get_db().commit()
        flash("Price guide entry added.", "success")
    except sqlite3.IntegrityError:
        flash("An entry for that kava type and month already exists.", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/prices/<int:price_id>/delete", methods=["POST"])
@admin_required
def admin_delete_price(price_id):
    get_db().execute("DELETE FROM price_guide WHERE id=?", (price_id,))
    get_db().commit()
    flash("Price guide entry deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.context_processor
def template_globals():
    return {"LOCATIONS": LOCATIONS, "KAVA_TYPES": KAVA_TYPES, "DRYING_OPTIONS": DRYING}


if __name__ == "__main__":
    if not os.path.exists(app.config["DATABASE"]):
        init_db()
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
