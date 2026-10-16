PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('farmer','buyer','exporter','admin')),
    phone TEXT DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    business_name TEXT DEFAULT '',
    bio TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','deactivated')),
    admin_note TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_status_role ON users(status, role);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id INTEGER NOT NULL REFERENCES users(id),
    kava_type TEXT NOT NULL,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit TEXT NOT NULL DEFAULT 'kg' CHECK(unit IN ('kg','bags')),
    drying_status TEXT NOT NULL CHECK(drying_status IN ('Fresh','Partly dried','Fully dried')),
    location TEXT NOT NULL,
    price REAL NOT NULL CHECK(price >= 0),
    currency TEXT NOT NULL DEFAULT 'FJD',
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','inactive','removed')),
    admin_note TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_farmer ON listings(farmer_id);
CREATE INDEX IF NOT EXISTS idx_listings_location ON listings(location);
CREATE INDEX IF NOT EXISTS idx_listings_type ON listings(kava_type);
CREATE INDEX IF NOT EXISTS idx_listings_drying ON listings(drying_status);
CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price);

CREATE TABLE IF NOT EXISTS listing_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_listing_images_listing ON listing_images(listing_id, sort_order);

CREATE TABLE IF NOT EXISTS enquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    buyer_id INTEGER NOT NULL REFERENCES users(id),
    farmer_id INTEGER NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL DEFAULT 'Kava enquiry',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(listing_id, buyer_id, farmer_id)
);
CREATE INDEX IF NOT EXISTS idx_enquiries_farmer ON enquiries(farmer_id);
CREATE INDEX IF NOT EXISTS idx_enquiries_buyer ON enquiries(buyer_id);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enquiry_id INTEGER NOT NULL REFERENCES enquiries(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_enquiry ON messages(enquiry_id, created_at);

CREATE TABLE IF NOT EXISTS price_guide (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kava_type TEXT NOT NULL,
    month TEXT NOT NULL,
    price_per_kg REAL NOT NULL CHECK(price_per_kg >= 0),
    notes TEXT DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(kava_type, month)
);
CREATE INDEX IF NOT EXISTS idx_price_guide_month_type ON price_guide(month, kava_type);
