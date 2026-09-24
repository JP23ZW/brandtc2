"""Account provisioning, project assignments and audited administration."""
import json
import os
import storage
from access_control import ROLES, PROJECT_ROLES, PERMISSIONS, current_user, require

ROOT_EMAIL = 'jprikken@triacon.nl'


def migrate_access(con):
    columns = storage._columns(con, 'users')
    for name, definition in {
        'role': "TEXT NOT NULL DEFAULT 'adviseur'",
        'can_create_project': 'INTEGER NOT NULL DEFAULT 0',
        'must_change_password': 'INTEGER NOT NULL DEFAULT 0',
        'session_version': 'INTEGER NOT NULL DEFAULT 1',
    }.items():
        if name not in columns:
            con.execute(f'ALTER TABLE users ADD COLUMN {name} {definition}')
    con.execute('CREATE TABLE IF NOT EXISTS project_members(project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL, permissions_json TEXT NOT NULL DEFAULT \'{}\', PRIMARY KEY(project_id,user_id))')
    con.execute('CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, target TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS login_attempts(email TEXT PRIMARY KEY, failures INTEGER NOT NULL, last_attempt REAL NOT NULL, blocked_until REAL NOT NULL DEFAULT 0)')
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_superadmin ON users(role) WHERE role='superadmin'")
    if not con.execute("SELECT 1 FROM app_settings WHERE key='access_migrated'").fetchone():
        # Preserve access for existing contributors, not for every account.
        con.execute("""INSERT OR IGNORE INTO project_members(project_id,user_id,role)
            SELECT id,created_by,'adviseur' FROM projects WHERE created_by IS NOT NULL
            UNION SELECT c.project_id,r.created_by,'adviseur' FROM reports r JOIN complexes c ON c.id=r.complex_id WHERE r.created_by IS NOT NULL
            UNION SELECT c.project_id,f.created_by,'adviseur' FROM findings f JOIN reports r ON r.id=f.report_id JOIN complexes c ON c.id=r.complex_id WHERE f.created_by IS NOT NULL""")
        con.execute("INSERT INTO app_settings VALUES('access_migrated','1')")


def _audit(con, actor, action, target, details):
    con.execute('INSERT INTO audit_log(actor_id,action,target,details,created_at) VALUES(?,?,?,?,?)',
                (actor, action, str(target), json.dumps(details, ensure_ascii=False), storage.now_iso()))


def bootstrap_admin(password):
    """Server-only, one-time provisioning; never called with browser input.

    Supply via deployment secret or the local provisioning command. No shared
    password, password hash or backdoor is shipped in the source repository.
    """
    if not password or len(password) < 12:
        raise ValueError('Het startwachtwoord moet minimaal 12 tekens bevatten.')
    with storage.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        existing = con.execute("SELECT value FROM app_settings WHERE key='root_provisioned'").fetchone()
        if existing:
            return int(existing['value'])
        stamp = storage.now_iso()
        row = con.execute('SELECT id FROM users WHERE email=? COLLATE NOCASE', (ROOT_EMAIL,)).fetchone()
        encoded = storage.hash_password(password)
        if row:
            uid = int(row['id'])
            con.execute("UPDATE users SET name='Joost Prikken',password_hash=?,role='superadmin',is_active=1,can_create_project=1,must_change_password=1,session_version=session_version+1,updated_at=? WHERE id=?", (encoded, stamp, uid))
        else:
            uid = con.execute("INSERT INTO users(name,email,password_hash,role,is_active,can_create_project,must_change_password,created_at,updated_at) VALUES(?,?,?,'superadmin',1,1,1,?,?)", ('Joost Prikken', ROOT_EMAIL, encoded, stamp, stamp)).lastrowid
        con.execute("INSERT INTO app_settings VALUES('root_provisioned',?)", (str(uid),))
        _audit(con, uid, 'bootstrap_admin', uid, {'email': ROOT_EMAIL})
        return int(uid)


def bootstrap_from_environment():
    secret = os.environ.get('BRANDVEILIGHEID_BOOTSTRAP_PASSWORD')
    if secret:
        bootstrap_admin(secret)


def list_users():
    require('manage_users')
    with storage.connect() as con:
        return [dict(r) for r in con.execute('SELECT id,name,email,role,is_active,can_create_project,must_change_password FROM users ORDER BY name,email')]


def update_user(user_id, role, active, can_create_project):
    if role not in ROLES or role == 'superadmin':
        raise ValueError('Ongeldige rol. De hoofdbeheerder wordt uitsluitend bij installatie ingesteld.')
    with storage.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        require('manage_users', con=con)
        actor = current_user(con)
        target = con.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if target is None or target['role'] == 'superadmin':
            raise PermissionError('Het hoofdbeheerdersaccount kan niet worden aangepast of geblokkeerd.')
        if target['role'] == 'admin' or role == 'admin':
            require('manage_admins', con=con)
        if actor['id'] == user_id:
            raise ValueError('Je kunt je eigen rechten hier niet wijzigen.')
        con.execute('UPDATE users SET role=?,is_active=?,can_create_project=?,session_version=session_version+1,updated_at=? WHERE id=?',
                    (role, int(active), int(can_create_project), storage.now_iso(), user_id))
        _audit(con, actor['id'], 'update_user', user_id, {'role': role, 'active': bool(active), 'create_project': bool(can_create_project)})


def reset_password(user_id, password):
    if len(password) < 12:
        raise ValueError('Gebruik minimaal 12 tekens voor het tijdelijke wachtwoord.')
    with storage.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        require('manage_users', con=con)
        target = con.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
        if target is None or target['role'] == 'superadmin':
            raise PermissionError('Het wachtwoord van de hoofdbeheerder kan hier niet worden gereset.')
        if target['role'] == 'admin':
            require('manage_admins', con=con)
        con.execute('UPDATE users SET password_hash=?,must_change_password=1,session_version=session_version+1,updated_at=? WHERE id=?', (storage.hash_password(password), storage.now_iso(), user_id))
        _audit(con, current_user(con)['id'], 'reset_password', user_id, {})


def memberships(project_id):
    require('manage_users')
    with storage.connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM project_members WHERE project_id=?', (project_id,))]


def assign_project(project_id, user_id, role, permissions):
    if role not in PROJECT_ROLES or set(permissions) - set(PERMISSIONS) or any(type(v) is not bool for v in permissions.values()):
        raise ValueError('Ongeldige projectrechten.')
    with storage.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        require('manage_users', con=con)
        target = con.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
        if target is None or target['role'] in ('admin', 'superadmin'):
            raise ValueError('Beheerders hebben al toegang tot alle projecten.')
        con.execute('INSERT INTO project_members(project_id,user_id,role,permissions_json) VALUES(?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role,permissions_json=excluded.permissions_json', (project_id, user_id, role, json.dumps(permissions)))
        _audit(con, current_user(con)['id'], 'assign_project', project_id, {'user_id': user_id, 'role': role, 'permissions': permissions})


def remove_project_member(project_id, user_id):
    with storage.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        require('manage_users', con=con)
        con.execute('DELETE FROM project_members WHERE project_id=? AND user_id=?', (project_id, user_id))
        _audit(con, current_user(con)['id'], 'remove_member', project_id, {'user_id': user_id})


def recent_audit():
    require('manage_users')
    with storage.connect() as con:
        return [dict(r) for r in con.execute('SELECT a.created_at,u.name AS beheerder,a.action,a.target,a.details FROM audit_log a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 100')]
