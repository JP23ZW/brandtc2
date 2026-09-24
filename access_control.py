"""Fail-closed, per-session authorization shared by UI and data services."""
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import inspect
import json

ACTOR = ContextVar('inspection_actor', default=None)
ROLES = {'superadmin': 'Hoofdbeheerder', 'admin': 'Beheerder', 'projectleider': 'Projectleider',
         'adviseur': 'Adviseur', 'lezer': 'Meelezer'}
PERMISSIONS = {'view': 'Project bekijken', 'edit_project': 'Projectgegevens wijzigen',
               'create_complex': 'Complexen aanmaken', 'edit_complex': 'Complexgegevens wijzigen',
               'create_report': 'Rapporten aanmaken en inlezen', 'edit_report': 'Rapporten en bevindingen wijzigen',
               'delete_finding': 'Bevindingen verwijderen', 'export': 'Rapporten en tekeningen exporteren'}
PROJECT_ROLES = {
    'projectleider': set(PERMISSIONS),
    'adviseur': {'view', 'create_report', 'edit_report', 'export'},
    'lezer': {'view'},
}


def set_actor(user_id=None, session_version=None):
    ACTOR.set((int(user_id), int(session_version)) if user_id is not None else None)


@contextmanager
def actor_session(user):
    token = ACTOR.set((int(user['id']), int(user['session_version'])))
    try:
        yield
    finally:
        ACTOR.reset(token)


def current_user(con=None):
    import storage
    actor = ACTOR.get()
    if actor is None:
        raise PermissionError('Log eerst in.')
    if con is None:
        with storage.connect() as db:
            return current_user(db)
    row = con.execute('SELECT id,name,email,role,is_active,session_version,must_change_password,can_create_project FROM users WHERE id=?', (actor[0],)).fetchone()
    if row is None or not row['is_active'] or row['session_version'] != actor[1]:
        raise PermissionError('Je sessie is verlopen of je account is geblokkeerd. Log opnieuw in.')
    return dict(row)


def allowed(permission, project_id=None, con=None):
    import storage
    if con is None:
        with storage.connect() as db:
            return allowed(permission, project_id, db)
    try:
        user = current_user(con)
    except PermissionError:
        return False
    if user['must_change_password']:
        return False
    if permission == 'manage_admins':
        return user['role'] == 'superadmin'
    if user['role'] in ('superadmin', 'admin'):
        return True
    if permission in ('manage_users', 'backup'):
        return False
    if permission == 'create_project':
        return bool(user['can_create_project'])
    if project_id is None or permission not in PERMISSIONS:
        return False
    row = con.execute('SELECT role,permissions_json FROM project_members WHERE project_id=? AND user_id=?', (project_id, user['id'])).fetchone()
    if row is None:
        return False
    permissions = set(PROJECT_ROLES.get(row['role'], set()))
    for key, value in json.loads(row['permissions_json']).items():
        if value is True:
            permissions.add(key)
        elif value is False:
            permissions.discard(key)
    return 'view' in permissions and permission in permissions


def require(permission, project_id=None, con=None):
    if not allowed(permission, project_id, con):
        raise PermissionError('Je hebt geen rechten voor deze handeling of dit project.')


def project_for(kind, object_id, con=None):
    import storage
    if con is None:
        with storage.connect() as db:
            return project_for(kind, object_id, db)
    queries = {
        'project': 'SELECT id FROM projects WHERE id=?',
        'complex': 'SELECT project_id FROM complexes WHERE id=?',
        'report': 'SELECT c.project_id FROM reports r JOIN complexes c ON c.id=r.complex_id WHERE r.id=?',
        'finding': 'SELECT c.project_id FROM findings f JOIN reports r ON r.id=f.report_id JOIN complexes c ON c.id=r.complex_id WHERE f.id=?',
        'drawing': 'SELECT c.project_id FROM drawings d JOIN reports r ON r.id=d.report_id JOIN complexes c ON c.id=r.complex_id WHERE d.id=?',
    }
    row = con.execute(queries[kind], (object_id,)).fetchone()
    if row is None:
        raise PermissionError('Project of onderdeel niet beschikbaar.')
    return int(row[0])


def require_object(permission, kind, object_id):
    require(permission, project_for(kind, object_id))


def guard(permission, kind=None, argument=None):
    def decorate(fn):
        signature = inspect.signature(fn)
        @wraps(fn)
        def checked(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            user = current_user()
            if 'user_id' in bound.arguments and int(bound.arguments['user_id']) != user['id']:
                raise PermissionError('Ongeldige gebruiker voor deze handeling.')
            project_id = project_for(kind, bound.arguments[argument]) if kind else None
            require(permission, project_id)
            return fn(*args, **kwargs)
        return checked
    return decorate
