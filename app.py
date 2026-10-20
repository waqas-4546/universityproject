import os
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, g, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "university.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "dev-only-change-this-secret"
)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")

    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            semester INTEGER NOT NULL
                CHECK (semester BETWEEN 1 AND 8)
        );

        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            credit_hours INTEGER NOT NULL
                CHECK (credit_hours BETWEEN 1 AND 6)
        );
    """)

    existing = db.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if existing is None:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash("Admin@123"))
        )

    db.commit()
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if user and check_password_hash(
            user["password_hash"], password
        ):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    counts = {}

    for table in ("students", "teachers", "courses"):
        counts[table] = db.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]

    return render_template("dashboard.html", counts=counts)


# Each section defines its database table and editable fields.
SECTIONS = {
    "students": {
        "title": "Students",
        "fields": [
            ("name", "Full Name", "text"),
            ("email", "Email", "email"),
            ("department", "Department", "text"),
            ("semester", "Semester (1-8)", "number"),
        ],
        "columns": ["name", "email", "department", "semester"],
    },
    "teachers": {
        "title": "Teachers",
        "fields": [
            ("name", "Full Name", "text"),
            ("email", "Email", "email"),
            ("department", "Department", "text"),
        ],
        "columns": ["name", "email", "department"],
    },
    "courses": {
        "title": "Courses",
        "fields": [
            ("name", "Course Name", "text"),
            ("code", "Course Code", "text"),
            ("department", "Department", "text"),
            ("credit_hours", "Credit Hours (1-6)", "number"),
        ],
        "columns": ["name", "code", "department", "credit_hours"],
    },
}


@app.route("/<section>", methods=["GET", "POST"])
@login_required
def manage_section(section):
    if section not in SECTIONS:
        abort(404)

    config = SECTIONS[section]
    db = get_db()
    fields = config["fields"]
    columns = config["columns"]

    if request.method == "POST":
        values = {}

        for field, label, kind in fields:
            value = request.form.get(field, "").strip()

            if not value:
                flash(f"{label} is required.", "error")
                return redirect(url_for("manage_section",
                                        section=section))

            if kind == "number":
                try:
                    value = int(value)
                except ValueError:
                    flash(f"{label} must be a number.", "error")
                    return redirect(url_for("manage_section",
                                            section=section))

            values[field] = value

        if section == "students" and not 1 <= values["semester"] <= 8:
            flash("Semester must be between 1 and 8.", "error")
            return redirect(url_for("manage_section", section=section))

        if section == "courses" and not 1 <= values["credit_hours"] <= 6:
            flash("Credit hours must be between 1 and 6.", "error")
            return redirect(url_for("manage_section", section=section))

        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)

        try:
            db.execute(
                f"INSERT INTO {section} ({column_sql}) "
                f"VALUES ({placeholders})",
                tuple(values[column] for column in columns)
            )
            db.commit()
            flash(f"{config['title']} record added successfully.", "success")
        except sqlite3.IntegrityError:
            flash("A record with this email or code already exists.", "error")

        return redirect(url_for("manage_section", section=section))

    records = db.execute(
        f"SELECT * FROM {section} ORDER BY id DESC"
    ).fetchall()

    return render_template(
        "students.html",
        section=section,
        config=config,
        records=records
    )


@app.post("/<section>/delete/<int:record_id>")
@login_required
def delete_record(section, record_id):
    if section not in SECTIONS:
        abort(404)

    db = get_db()
    db.execute(f"DELETE FROM {section} WHERE id = ?", (record_id,))
    db.commit()
    flash("Record deleted.", "success")
    return redirect(url_for("manage_section", section=section))


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)