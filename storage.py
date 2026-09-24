from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
BUNDLED_DATA_DIR = APP_DIR / "data"


def _default_data_dir() -> Path:
    configured = os.environ.get("BRANDVEILIGHEID_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Triacon" / "Brandveiligheidsinspectie"
    return Path.home() / ".triacon" / "brandveiligheidsinspectie"


# User-created data lives outside the app folder, so installing or starting a
# different app copy can never silently switch to an empty bundled database.
DATA_DIR = _default_data_dir()
DB_PATH = Path(os.environ.get("BRANDVEILIGHEID_DB", DATA_DIR / "brandveiligheid.db"))
PASSWORD_ITERATIONS = 600_000


class ManagedConnection(sqlite3.Connection):
    """Commit/rollback and always release the Windows file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30.0, factory=ManagedConnection)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}


def _create_current_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            client TEXT,
            project_number TEXT,
            description TEXT,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS complexes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            complex_number TEXT,
            address TEXT,
            postal_code TEXT,
            city TEXT,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complex_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Concept',
            data_json TEXT NOT NULL DEFAULT '{}',
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(complex_id) REFERENCES complexes(id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            finding_type TEXT NOT NULL DEFAULT 'Maatregel',
            code_group TEXT NOT NULL DEFAULT 'G',
            code_number INTEGER NOT NULL,
            discipline TEXT NOT NULL DEFAULT 'Bouwkundig',
            onderwerp TEXT,
            tekeningnummer TEXT,
            bouwlaag TEXT,
            ruimte TEXT,
            eis TEXT,
            gebrek TEXT,
            aantal TEXT,
            afmeting TEXT,
            maatregel TEXT,
            opmerking TEXT,
            richtlijn TEXT,
            cost_items TEXT NOT NULL DEFAULT '[]',
            photo_before TEXT,
            photo_after TEXT,
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(report_id, code_group, code_number)
        );

        CREATE INDEX IF NOT EXISTS idx_complexes_project ON complexes(project_id);
        CREATE INDEX IF NOT EXISTS idx_reports_complex ON reports(complex_id);
        CREATE INDEX IF NOT EXISTS idx_findings_report ON findings(report_id);

        CREATE TABLE IF NOT EXISTS drawings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            drawing_number TEXT NOT NULL DEFAULT '',
            floor TEXT NOT NULL DEFAULT '',
            page_number INTEGER NOT NULL,
            original_path TEXT NOT NULL,
            image_path TEXT NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_drawings_report ON drawings(report_id);
        CREATE TABLE IF NOT EXISTS finding_locations (
            finding_id INTEGER PRIMARY KEY REFERENCES findings(id) ON DELETE CASCADE,
            drawing_id INTEGER NOT NULL REFERENCES drawings(id) ON DELETE CASCADE,
            x REAL NOT NULL CHECK(x >= 0 AND x <= 1),
            y REAL NOT NULL CHECK(y >= 0 AND y <= 1)
        );
        CREATE INDEX IF NOT EXISTS idx_locations_drawing ON finding_locations(drawing_id);
        CREATE TRIGGER IF NOT EXISTS location_same_report
        BEFORE INSERT ON finding_locations
        WHEN (SELECT report_id FROM findings WHERE id=NEW.finding_id)
          != (SELECT report_id FROM drawings WHERE id=NEW.drawing_id)
        BEGIN SELECT RAISE(ABORT, 'Tekening en bevinding horen niet bij hetzelfde rapport.'); END;
        """
    )


def _ensure_current_columns(con: sqlite3.Connection) -> None:
    finding_columns = _columns(con, "findings")
    if finding_columns and "cost_items" not in finding_columns:
        con.execute("ALTER TABLE findings ADD COLUMN cost_items TEXT NOT NULL DEFAULT '[]'")


def _backup_legacy_database() -> None:
    backup = DB_PATH.parent / "brandveiligheid-pre-multiuser.backup.db"
    if DB_PATH.exists() and not backup.exists():
        shutil.copy2(DB_PATH, backup)


def _migrate_legacy_schema(con: sqlite3.Connection) -> None:
    legacy_columns = _columns(con, "projects")
    if "data_json" not in legacy_columns or "reports" in {
        row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }:
        return

    _backup_legacy_database()
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("ALTER TABLE projects RENAME TO legacy_reports")
    if _table_exists(con, "findings"):
        con.execute("ALTER TABLE findings RENAME TO legacy_findings")
    _create_current_schema(con)

    legacy_reports = con.execute("SELECT * FROM legacy_reports ORDER BY id").fetchall()
    for row in legacy_reports:
        data = json.loads(row["data_json"] or "{}")
        stamp_created = row["created_at"] or now_iso()
        stamp_updated = row["updated_at"] or stamp_created
        project_name = data.get("projectnaam") or row["title"] or "Gemigreerd project"
        project_cur = con.execute(
            "INSERT INTO projects(name,client,project_number,description,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (
                project_name,
                data.get("opdrachtgever", ""),
                data.get("projectnummer", ""),
                "Automatisch gemigreerd uit de eerdere rapportstructuur.",
                stamp_created,
                stamp_updated,
            ),
        )
        complex_cur = con.execute(
            """INSERT INTO complexes(project_id,name,complex_number,address,postal_code,city,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                project_cur.lastrowid,
                data.get("complexnaam") or row["title"] or "Gemigreerd complex",
                data.get("complexnummer", ""),
                data.get("projectadres", ""),
                data.get("postcode", ""),
                data.get("plaats", ""),
                stamp_created,
                stamp_updated,
            ),
        )
        con.execute(
            """INSERT INTO reports(id,complex_id,title,status,data_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                row["id"],
                complex_cur.lastrowid,
                row["title"],
                row["status"],
                row["data_json"],
                stamp_created,
                stamp_updated,
            ),
        )

    if _table_exists(con, "legacy_findings"):
        old_cols = _columns(con, "legacy_findings")
        copy_cols = [
            "id", "finding_type", "code_group", "code_number", "discipline", "onderwerp",
            "tekeningnummer", "bouwlaag", "ruimte", "eis", "gebrek", "aantal", "afmeting",
            "maatregel", "opmerking", "richtlijn", "photo_before", "photo_after", "created_at", "updated_at",
        ]
        for row in con.execute("SELECT * FROM legacy_findings ORDER BY id").fetchall():
            values = [row[col] if col in old_cols else "" for col in copy_cols]
            con.execute(
                f"INSERT INTO findings(report_id,{','.join(copy_cols)}) VALUES({','.join('?' for _ in range(len(copy_cols) + 1))})",
                [row["project_id"]] + values,
            )
        con.execute("DROP TABLE legacy_findings")
    con.execute("DROP TABLE legacy_reports")
    con.execute("PRAGMA foreign_keys=ON")


def _copy_database(source: Path, target: Path) -> None:
    """Create a consistent SQLite copy, including any committed WAL changes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source, timeout=30.0)
    target_connection = sqlite3.connect(target, timeout=30.0)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _bootstrap_persistent_storage() -> None:
    """Move the last bundled database/uploads to the durable user-data folder once."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    bundled_database = BUNDLED_DATA_DIR / "brandveiligheid.db"
    if not DB_PATH.exists() and bundled_database.exists() and DB_PATH.resolve() != bundled_database.resolve():
        _copy_database(bundled_database, DB_PATH)

    bundled_uploads = BUNDLED_DATA_DIR / "uploads"
    persistent_uploads = DB_PATH.parent / "uploads"
    if bundled_uploads.exists() and bundled_uploads.resolve() != persistent_uploads.resolve():
        shutil.copytree(bundled_uploads, persistent_uploads, dirs_exist_ok=True)


def create_database_backup(label: str = "handmatig") -> Path:
    """Write a transactionally consistent database snapshot and return its path."""
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(character for character in label.lower() if character.isalnum() or character in "-_") or "backup"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = backup_dir / f"brandveiligheid-{safe_label}-{stamp}.db"
    _copy_database(DB_PATH, target)
    return target


def _ensure_daily_backup() -> None:
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"brandveiligheid-dagbackup-{date.today():%Y%m%d}.db"
    if not target.exists():
        _copy_database(DB_PATH, target)


def database_status() -> dict:
    with connect() as con:
        counts = {
            table: int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("users", "projects", "complexes", "reports", "findings")
        }
        integrity = str(con.execute("PRAGMA quick_check").fetchone()[0])
    return {
        "path": str(DB_PATH.resolve()),
        "size": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "integrity": integrity,
        **counts,
    }


def init_db() -> None:
    _bootstrap_persistent_storage()
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH, factory=ManagedConnection) as check:
            previous_version = check.execute("PRAGMA user_version").fetchone()[0]
            needs_drawing_migration = previous_version < 4
        migration_backup = DB_PATH.parent / "backups" / "brandveiligheid-voor-tekeningen.db"
        if needs_drawing_migration and not migration_backup.exists():
            _copy_database(DB_PATH, migration_backup)
        access_backup = DB_PATH.parent / 'backups' / 'brandveiligheid-voor-rechten.db'
        if previous_version < 5 and not access_backup.exists():
            _copy_database(DB_PATH, access_backup)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        _migrate_legacy_schema(con)
        _create_current_schema(con)
        _ensure_current_columns(con)
        from user_admin import migrate_access
        migrate_access(con)
        con.execute("PRAGMA user_version=5")
    from user_admin import bootstrap_from_environment
    bootstrap_from_environment()
    _ensure_daily_backup()


def hash_password(password: str, iterations: int = PASSWORD_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(iterations),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_text))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register_user(name: str, email: str, password: str) -> int:
    name = name.strip()
    email = normalize_email(email)
    from user_admin import ROOT_EMAIL
    if email == ROOT_EMAIL:
        raise ValueError('Dit account is gereserveerd voor de hoofdbeheerder.')
    if not name:
        raise ValueError("Vul uw naam in.")
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise ValueError("Vul een geldig e-mailadres in.")
    if len(password) < 10:
        raise ValueError("Gebruik een wachtwoord van minimaal 10 tekens.")
    stamp = now_iso()
    try:
        with connect() as con:
            cur = con.execute(
                "INSERT INTO users(name,email,password_hash,created_at,updated_at,is_active) VALUES(?,?,?,?,?,0)",
                (name, email, hash_password(password), stamp, stamp),
            )
            return int(cur.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ValueError("Voor dit e-mailadres bestaat al een account.") from exc


def authenticate_user(email: str, password: str) -> dict | None:
    email = normalize_email(email)
    now = time.time()
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        attempt = con.execute('SELECT * FROM login_attempts WHERE email=?', (email,)).fetchone()
        if attempt and attempt['blocked_until'] > now:
            return None
        row = con.execute(
            "SELECT * FROM users WHERE email=? COLLATE NOCASE AND is_active=1",
            (email,),
        ).fetchone()
        if row is None or not verify_password(password, row['password_hash']):
            failures = attempt['failures'] + 1 if attempt and now - attempt['last_attempt'] < 900 else 1
            con.execute('INSERT INTO login_attempts(email,failures,last_attempt,blocked_until) VALUES(?,?,?,?) ON CONFLICT(email) DO UPDATE SET failures=excluded.failures,last_attempt=excluded.last_attempt,blocked_until=excluded.blocked_until',
                        (email, failures, now, now + 300 if failures >= 5 else 0))
            return None
        con.execute('DELETE FROM login_attempts WHERE email=?', (email,))
        return {key: row[key] for key in ('id', 'name', 'email', 'role', 'is_active', 'session_version', 'must_change_password', 'can_create_project')}


def get_user(user_id: int) -> dict | None:
    with connect() as con:
        row = con.execute(
            "SELECT id,name,email,role,is_active,session_version,must_change_password,can_create_project FROM users WHERE id=? AND is_active=1", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def change_password(user_id: int, current_password: str, new_password: str) -> None:
    from access_control import current_user
    if current_user()['id'] != user_id:
        raise PermissionError('Je kunt alleen je eigen wachtwoord wijzigen.')
    with connect() as con:
        row = con.execute("SELECT password_hash FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone()
        if row is None or not verify_password(current_password, row["password_hash"]):
            raise ValueError("Het huidige wachtwoord is niet correct.")
        if len(new_password) < 10:
            raise ValueError("Gebruik een nieuw wachtwoord van minimaal 10 tekens.")
        if verify_password(new_password, row['password_hash']):
            raise ValueError('Kies een ander wachtwoord dan het huidige wachtwoord.')
        con.execute(
            "UPDATE users SET password_hash=?,updated_at=?,must_change_password=0,session_version=session_version+1 WHERE id=?",
            (hash_password(new_password), now_iso(), user_id),
        )


def list_projects() -> list[sqlite3.Row]:
    from access_control import current_user, allowed
    current_user()
    with connect() as con:
        rows = con.execute(
            """SELECT p.*, COUNT(DISTINCT c.id) AS complex_count, COUNT(DISTINCT r.id) AS report_count
               FROM projects p
               LEFT JOIN complexes c ON c.project_id=p.id
               LEFT JOIN reports r ON r.complex_id=c.id
               GROUP BY p.id ORDER BY p.updated_at DESC, p.name"""
        ).fetchall()
        return [row for row in rows if allowed('view', row['id'], con)]


def create_project(name: str, client: str, project_number: str, description: str, user_id: int) -> int:
    if not name.strip():
        raise ValueError("Vul een projectnaam in.")
    stamp = now_iso()
    with connect() as con:
        cur = con.execute(
            """INSERT INTO projects(name,client,project_number,description,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (name.strip(), client.strip(), project_number.strip(), description.strip(), user_id, stamp, stamp),
        )
        role = con.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()['role']
        con.execute('INSERT INTO project_members(project_id,user_id,role) VALUES(?,?,?)',
                    (cur.lastrowid, user_id, role if role in ('projectleider','adviseur','lezer') else 'projectleider'))
        return int(cur.lastrowid)


def load_project(project_id: int) -> dict:
    with connect() as con:
        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise KeyError(project_id)
    return dict(row)


def update_project(project_id: int, payload: dict) -> None:
    with connect() as con:
        con.execute(
            "UPDATE projects SET name=?,client=?,project_number=?,description=?,updated_at=? WHERE id=?",
            (
                payload.get("name", "").strip() or "Naamloos project",
                payload.get("client", "").strip(),
                payload.get("project_number", "").strip(),
                payload.get("description", "").strip(),
                now_iso(),
                project_id,
            ),
        )


def list_complexes(project_id: int) -> list[sqlite3.Row]:
    with connect() as con:
        return con.execute(
            """SELECT c.*, COUNT(r.id) AS report_count FROM complexes c
               LEFT JOIN reports r ON r.complex_id=c.id
               WHERE c.project_id=? GROUP BY c.id ORDER BY c.updated_at DESC,c.name""",
            (project_id,),
        ).fetchall()


def create_complex(project_id: int, name: str, complex_number: str, address: str, postal_code: str, city: str, user_id: int) -> int:
    if not name.strip():
        raise ValueError("Vul een complexnaam in.")
    stamp = now_iso()
    with connect() as con:
        cur = con.execute(
            """INSERT INTO complexes(project_id,name,complex_number,address,postal_code,city,created_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (project_id, name.strip(), complex_number.strip(), address.strip(), postal_code.strip(), city.strip(), user_id, stamp, stamp),
        )
        con.execute("UPDATE projects SET updated_at=? WHERE id=?", (stamp, project_id))
        return int(cur.lastrowid)


def load_complex(complex_id: int) -> dict:
    with connect() as con:
        row = con.execute("SELECT * FROM complexes WHERE id=?", (complex_id,)).fetchone()
    if row is None:
        raise KeyError(complex_id)
    return dict(row)


def update_complex(complex_id: int, payload: dict) -> None:
    with connect() as con:
        con.execute(
            """UPDATE complexes SET name=?,complex_number=?,address=?,postal_code=?,city=?,updated_at=? WHERE id=?""",
            (
                payload.get("name", "").strip() or "Naamloos complex",
                payload.get("complex_number", "").strip(),
                payload.get("address", "").strip(),
                payload.get("postal_code", "").strip(),
                payload.get("city", "").strip(),
                now_iso(),
                complex_id,
            ),
        )


def list_reports(complex_id: int) -> list[sqlite3.Row]:
    with connect() as con:
        return con.execute(
            "SELECT * FROM reports WHERE complex_id=? ORDER BY updated_at DESC,title", (complex_id,)
        ).fetchall()


def create_report(complex_id: int, title: str, user_id: int) -> int:
    title = title.strip() or "Rapportage brandveiligheid"
    data = {
        "report_date": date.today().strftime("%d-%m-%Y"),
        "version": "0.1",
        "gelijkwaardigheid": "In dit complex zijn geen gelijkwaardigheidsoplossingen van toepassing.",
    }
    stamp = now_iso()
    with connect() as con:
        cur = con.execute(
            """INSERT INTO reports(complex_id,title,status,data_json,created_by,updated_by,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (complex_id, title, "Concept", json.dumps(data, ensure_ascii=False), user_id, user_id, stamp, stamp),
        )
        return int(cur.lastrowid)


CONTEXT_KEYS = {
    "id", "title", "status", "complex_id", "project_id", "projectnaam", "projectnummer",
    "opdrachtgever", "complexnummer", "complexnaam", "projectadres", "postcode", "plaats",
}


def load_report(report_id: int) -> dict:
    with connect() as con:
        row = con.execute(
            """SELECT r.*,c.project_id,c.name AS complexnaam,c.complex_number AS complexnummer,
                      c.address AS projectadres,c.postal_code AS postcode,c.city AS plaats,
                      p.name AS projectnaam,p.client AS opdrachtgever,p.project_number AS projectnummer
               FROM reports r JOIN complexes c ON c.id=r.complex_id JOIN projects p ON p.id=c.project_id
               WHERE r.id=?""",
            (report_id,),
        ).fetchone()
    if row is None:
        raise KeyError(report_id)
    data = json.loads(row["data_json"] or "{}")
    for key in row.keys():
        if key != "data_json":
            data[key] = row[key]
    return data


def save_report(report_id: int, data: dict, user_id: int) -> None:
    clean = {key: value for key, value in data.items() if key not in CONTEXT_KEYS and key not in {"created_at", "updated_at", "created_by", "updated_by"}}
    with connect() as con:
        con.execute(
            "UPDATE reports SET title=?,status=?,data_json=?,updated_by=?,updated_at=? WHERE id=?",
            (
                data.get("title") or "Rapportage brandveiligheid",
                data.get("status") or "Concept",
                json.dumps(clean, ensure_ascii=False),
                user_id,
                now_iso(),
                report_id,
            ),
        )


def list_findings(report_id: int) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM findings WHERE report_id=? ORDER BY finding_type,code_group,code_number,id",
            (report_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def next_number(report_id: int, code_group: str) -> int:
    with connect() as con:
        row = con.execute(
            "SELECT COALESCE(MAX(code_number),0)+1 AS n FROM findings WHERE report_id=? AND code_group=?",
            (report_id, code_group),
        ).fetchone()
    return int(row["n"])


def insert_finding(report_id: int, payload: dict, user_id: int) -> int:
    columns = [
        "report_id", "finding_type", "code_group", "code_number", "discipline", "onderwerp",
        "tekeningnummer", "bouwlaag", "ruimte", "eis", "gebrek", "aantal", "afmeting",
        "maatregel", "opmerking", "richtlijn", "cost_items", "photo_before", "photo_after",
        "created_by", "updated_by", "created_at", "updated_at",
    ]
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        number = con.execute(
            "SELECT COALESCE(MAX(code_number),0)+1 FROM findings WHERE report_id=? AND code_group=?",
            (report_id, payload.get("code_group", "G")),
        ).fetchone()[0]
        payload = dict(payload)
        payload["code_number"] = int(number)
        stamp = now_iso()
        payload_columns = columns[1:-4]
        values = [report_id] + [payload.get(col, "") for col in payload_columns] + [user_id, user_id, stamp, stamp]
        cur = con.execute(
            f"INSERT INTO findings({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            values,
        )
        location = payload.get("drawing_location")
        if location:
            drawing = con.execute('SELECT report_id FROM drawings WHERE id=?', (int(location['drawing_id']),)).fetchone()
            if drawing is None or drawing['report_id'] != report_id:
                raise PermissionError('Deze tekening hoort niet bij dit rapport.')
            # Commit the finding and its position together; never create orphan pins.
            con.execute(
                "INSERT INTO finding_locations(finding_id,drawing_id,x,y) VALUES(?,?,?,?)",
                (cur.lastrowid, int(location["drawing_id"]), float(location["x"]), float(location["y"])),
            )
        return int(cur.lastrowid)


def list_drawings(report_id: int) -> list[dict]:
    with connect() as con:
        return [dict(row) for row in con.execute(
            "SELECT * FROM drawings WHERE report_id=? ORDER BY id", (report_id,)
        )]


def insert_drawings(report_id: int, pages: list[dict]) -> list[int]:
    ids = []
    with connect() as con:
        for page in pages:
            cursor = con.execute(
                """INSERT INTO drawings(report_id,name,drawing_number,floor,page_number,
                   original_path,image_path,width,height,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (report_id, page["name"], page["drawing_number"], page["floor"], page["page_number"],
                 page["original_path"], page["image_path"], page["width"], page["height"], now_iso()),
            )
            ids.append(int(cursor.lastrowid))
    return ids


def drawing_markers(drawing_id: int) -> list[dict]:
    with connect() as con:
        return [dict(row) for row in con.execute(
            """SELECT l.x,l.y,f.id AS finding_id,f.code_group,f.code_number,f.onderwerp
               FROM finding_locations l JOIN findings f ON f.id=l.finding_id
               WHERE l.drawing_id=? ORDER BY f.code_group,f.code_number""", (drawing_id,)
        )]


def update_finding(finding_id: int, payload: dict, user_id: int) -> None:
    columns = [
        "finding_type", "code_group", "code_number", "discipline", "onderwerp", "tekeningnummer",
        "bouwlaag", "ruimte", "eis", "gebrek", "aantal", "afmeting", "maatregel", "opmerking",
        "richtlijn", "cost_items", "photo_before", "photo_after",
    ]
    assignments = ",".join(f"{column}=?" for column in columns)
    with connect() as con:
        con.execute(
            f"UPDATE findings SET {assignments},updated_by=?,updated_at=? WHERE id=?",
            [payload.get(column, "") for column in columns] + [user_id, now_iso(), finding_id],
        )


def delete_finding(finding_id: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM findings WHERE id=?", (finding_id,))


# Enforce authorization for all public project data services, not only buttons.
from access_control import guard
for _function, _permission, _kind, _argument in [
    ('create_project', 'create_project', None, None),
    ('load_project', 'view', 'project', 'project_id'),
    ('update_project', 'edit_project', 'project', 'project_id'),
    ('list_complexes', 'view', 'project', 'project_id'),
    ('create_complex', 'create_complex', 'project', 'project_id'),
    ('load_complex', 'view', 'complex', 'complex_id'),
    ('update_complex', 'edit_complex', 'complex', 'complex_id'),
    ('list_reports', 'view', 'complex', 'complex_id'),
    ('create_report', 'create_report', 'complex', 'complex_id'),
    ('load_report', 'view', 'report', 'report_id'),
    ('save_report', 'edit_report', 'report', 'report_id'),
    ('list_findings', 'view', 'report', 'report_id'),
    ('next_number', 'view', 'report', 'report_id'),
    ('insert_finding', 'edit_report', 'report', 'report_id'),
    ('update_finding', 'edit_report', 'finding', 'finding_id'),
    ('delete_finding', 'delete_finding', 'finding', 'finding_id'),
    ('list_drawings', 'view', 'report', 'report_id'),
    ('insert_drawings', 'edit_report', 'report', 'report_id'),
    ('drawing_markers', 'view', 'drawing', 'drawing_id'),
    ('create_database_backup', 'backup', None, None),
    ('database_status', 'backup', None, None),
]:
    globals()[_function] = guard(_permission, _kind, _argument)(globals()[_function])
