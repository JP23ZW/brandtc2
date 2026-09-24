import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import storage
import user_admin
from access_control import set_actor, actor_session, allowed, require_object
from report_import import save_import
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches = [patch.object(storage, 'DATA_DIR', Path(self.tmp.name)),
                        patch.object(storage, 'DB_PATH', Path(self.tmp.name) / 'access.db'),
                        patch.object(storage, 'BUNDLED_DATA_DIR', Path(self.tmp.name) / 'empty')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(set_actor)
        storage.init_db()
        self.root_id = user_admin.bootstrap_admin('Initial-test-password!')
        root = storage.authenticate_user(user_admin.ROOT_EMAIL, 'Initial-test-password!')
        set_actor(root['id'], root['session_version'])
        self.assertFalse(allowed('create_project'))
        storage.change_password(root['id'], 'Initial-test-password!', 'Changed-test-password!')
        self.root = storage.authenticate_user(user_admin.ROOT_EMAIL, 'Changed-test-password!')
        set_actor(self.root['id'], self.root['session_version'])
        self.pid = storage.create_project('Assigned', '', '', '', self.root_id)
        self.other = storage.create_project('Hidden', '', '', '', self.root_id)
        self.cid = storage.create_complex(self.pid, 'Complex', '', '', '', '', self.root_id)
        self.rid = storage.create_report(self.cid, 'Report', self.root_id)
        self.uid = storage.register_user('Advisor', 'advisor@example.test', 'AdvisorPassword123!')
        user_admin.update_user(self.uid, 'adviseur', True, False)
        user_admin.assign_project(self.pid, self.uid, 'adviseur', {})
        self.advisor = storage.get_user(self.uid)

    def test_bootstrap_idempotent_and_root_protected(self):
        self.assertEqual(user_admin.bootstrap_admin('Different-password!'), self.root_id)
        self.assertIsNotNone(storage.authenticate_user(user_admin.ROOT_EMAIL, 'Changed-test-password!'))
        self.assertIsNone(storage.authenticate_user(user_admin.ROOT_EMAIL, 'Different-password!'))
        with self.assertRaises(PermissionError):
            user_admin.update_user(self.root_id, 'lezer', False, False)
        with self.assertRaises(PermissionError):
            user_admin.reset_password(self.root_id, 'OverwritePassword!')
        with self.assertRaises(ValueError):
            storage.register_user('Spoof', user_admin.ROOT_EMAIL, 'OverwritePassword!')
        storage.init_db()
        self.assertEqual(storage.get_user(self.root_id)['role'], 'superadmin')

    def test_cloud_bootstrap_reads_streamlit_secret(self):
        with patch.dict(user_admin.os.environ, {}, clear=True), \
             patch('streamlit.secrets', {'BRANDVEILIGHEID_BOOTSTRAP_PASSWORD': 'Cloud-test-password!'}), \
             patch.object(user_admin, 'bootstrap_admin') as bootstrap:
            user_admin.bootstrap_from_environment()
            bootstrap.assert_called_once_with('Cloud-test-password!')

    def test_no_auth_and_project_id_tampering(self):
        set_actor()
        for fn in [storage.list_projects, lambda: storage.load_report(self.rid), storage.create_database_backup]:
            with self.assertRaises(PermissionError):
                fn()
        with actor_session(self.advisor):
            self.assertEqual([p['id'] for p in storage.list_projects()], [self.pid])
            self.assertEqual(storage.load_report(self.rid)['id'], self.rid)
            for fn in [lambda: storage.load_project(self.other),
                       lambda: storage.create_project('Denied', '', '', '', self.uid),
                       lambda: storage.create_complex(self.pid, 'Denied', '', '', '', '', self.uid),
                       lambda: storage.create_report(self.cid, 'Spoofed actor', self.root_id),
                       storage.create_database_backup, user_admin.list_users]:
                with self.assertRaises(PermissionError):
                    fn()

    def test_permission_overrides_and_revocation(self):
        user_admin.assign_project(self.pid, self.uid, 'adviseur', {'create_complex': True, 'edit_report': False, 'export': False})
        with actor_session(self.advisor):
            storage.create_complex(self.pid, 'Allowed', '', '', '', '', self.uid)
            self.assertFalse(allowed('export', self.pid))
            with self.assertRaises(PermissionError):
                storage.save_report(self.rid, {'title': 'Denied'}, self.uid)
        user_admin.remove_project_member(self.pid, self.uid)
        with actor_session(self.advisor):
            with self.assertRaises(PermissionError):
                storage.load_report(self.rid)

    def test_separate_creation_right_and_no_admin_escalation(self):
        user_admin.update_user(self.uid, 'adviseur', True, True)
        advisor = storage.get_user(self.uid)
        with actor_session(advisor):
            pid = storage.create_project('Own project', '', '', '', self.uid)
            self.assertTrue(allowed('view', pid))
            self.assertFalse(allowed('create_complex', pid))
            with self.assertRaises(PermissionError):
                user_admin.assign_project(pid, self.uid, 'projectleider', {})
        user_admin.update_user(self.uid, 'admin', True, True)
        admin = storage.get_user(self.uid)
        other_user = storage.register_user('Other', 'other@example.test', 'OtherPassword123!')
        with actor_session(admin):
            with self.assertRaises(PermissionError):
                user_admin.update_user(other_user, 'admin', True, True)
            with self.assertRaises(PermissionError):
                user_admin.update_user(self.root_id, 'lezer', False, False)
            user_admin.update_user(other_user, 'adviseur', True, False)

    def test_session_identity_is_isolated_between_threads(self):
        barrier = Barrier(2)
        def check(user):
            with actor_session(user):
                barrier.wait(timeout=10)
                return {p['id'] for p in storage.list_projects()}
        with ThreadPoolExecutor(max_workers=2) as pool:
            root = pool.submit(check, self.root)
            advisor = pool.submit(check, self.advisor)
            self.assertEqual(root.result(), {self.pid, self.other})
            self.assertEqual(advisor.result(), {self.pid})

    def test_view_denial_overrides_all_other_permissions(self):
        user_admin.assign_project(self.pid, self.uid, 'projectleider', {'view': False, 'export': True})
        with actor_session(self.advisor):
            self.assertFalse(allowed('export', self.pid))
            self.assertEqual(storage.list_projects(), [])
            with self.assertRaises(PermissionError):
                storage.create_report(self.cid, 'Denied', self.uid)

    def test_pending_blocked_reset_and_throttle(self):
        pending = storage.register_user('Pending', 'pending@example.test', 'PendingPassword123!')
        self.assertIsNone(storage.authenticate_user('pending@example.test', 'PendingPassword123!'))
        user_admin.reset_password(self.uid, 'TemporaryPassword123!')
        with actor_session(self.advisor):
            with self.assertRaises(PermissionError):
                storage.load_report(self.rid)
        fresh = storage.authenticate_user('advisor@example.test', 'TemporaryPassword123!')
        self.assertTrue(fresh['must_change_password'])
        with actor_session(fresh):
            self.assertFalse(allowed('view', self.pid))
        user_admin.update_user(self.uid, 'adviseur', False, False)
        self.assertIsNone(storage.authenticate_user('advisor@example.test', 'TemporaryPassword123!'))
        for _ in range(5):
            storage.authenticate_user(user_admin.ROOT_EMAIL, 'wrong-password')
        self.assertIsNone(storage.authenticate_user(user_admin.ROOT_EMAIL, 'Changed-test-password!'))

    def test_import_and_cross_report_drawing_denied(self):
        user_admin.assign_project(self.pid, self.uid, 'lezer', {})
        with actor_session(self.advisor):
            with self.assertRaises(PermissionError):
                save_import({}, b'', self.cid, 'Denied', self.uid)
        self.assertFalse((Path(self.tmp.name) / 'uploads').exists())
        other_complex = storage.create_complex(self.other, 'Other', '', '', '', '', self.root_id)
        other_report = storage.create_report(other_complex, 'Other', self.root_id)
        did = storage.insert_drawings(other_report, [dict(name='Test',drawing_number='',floor='',page_number=1,original_path='',image_path='',width=1,height=1)])[0]
        user_admin.assign_project(self.pid, self.uid, 'adviseur', {})
        with actor_session(self.advisor):
            with self.assertRaises(PermissionError):
                storage.insert_finding(self.rid, dict(code_group='G',drawing_location=dict(drawing_id=did,x=.5,y=.5)), self.uid)
        self.assertEqual(storage.list_findings(self.rid), [])

    def test_ui_admin_reader_and_invalidated_session(self):
        path = str(Path(__file__).parent / 'app.py')
        at = AppTest.from_file(path, default_timeout=20)
        at.session_state['user_id'] = self.root_id
        at.session_state['auth_session_version'] = self.root['session_version']
        at.session_state['active_module'] = 'Beheer'
        at.run()
        self.assertFalse(at.exception)
        self.assertTrue(any(s.label == 'Gebruiker beheren' for s in at.selectbox))
        user_admin.assign_project(self.pid, self.uid, 'lezer', {})
        reader = AppTest.from_file(path, default_timeout=20)
        reader.session_state['user_id'] = self.uid
        reader.session_state['auth_session_version'] = self.advisor['session_version']
        reader.run()
        self.assertFalse(reader.exception)
        self.assertNotIn('Beheer', reader.radio[0].options)
        for label in ('Project aanmaken','Complex aanmaken','Rapport aanmaken'):
            self.assertTrue(next(b for b in reader.button if b.label == label).disabled)
        for tab in ('Rapportgegevens','Algemene gegevens','Situatie','Tekeningen','Inspectie','Bevindingen','Rapport'):
            reader.session_state['navigate_to'] = tab
            reader.run()
            self.assertFalse(reader.exception, tab)
        self.assertFalse(any(b.label == 'Word-rapport voorbereiden' for b in reader.button))
        user_admin.update_user(self.uid, 'lezer', False, False)
        reader.run()
        self.assertFalse(reader.exception)
        self.assertTrue(any(b.label == 'Inloggen' for b in reader.button))

    def test_ui_first_login_password_change_and_relogin(self):
        with storage.connect() as con:
            con.execute('UPDATE users SET must_change_password=1 WHERE id=?', (self.root_id,))
        at = AppTest.from_file(str(Path(__file__).parent / 'app.py'), default_timeout=20).run()
        def input_value(label, value):
            next(w for w in at.text_input if w.label == label).set_value(value)
        def click(label):
            next(b for b in at.button if b.label == label).click().run()
            self.assertFalse(at.exception)
        input_value('E-mailadres', user_admin.ROOT_EMAIL)
        input_value('Wachtwoord', 'Changed-test-password!')
        click('Inloggen')
        self.assertTrue(any('tijdelijke wachtwoord' in w.value for w in at.warning))
        input_value('Huidig wachtwoord', 'Changed-test-password!')
        input_value('Nieuw wachtwoord', 'New-login-password!')
        input_value('Nieuw wachtwoord bevestigen', 'New-login-password!')
        click('Wachtwoord wijzigen')
        input_value('E-mailadres', user_admin.ROOT_EMAIL)
        input_value('Wachtwoord', 'New-login-password!')
        click('Inloggen')
        self.assertTrue(any('Beheer' in r.options for r in at.radio))

    def test_login_after_waiting_on_login_screen(self):
        at = AppTest.from_file(str(Path(__file__).parent / 'app.py'), default_timeout=20).run()
        at.session_state['auth_last_activity'] = 1.0
        next(w for w in at.text_input if w.label == 'E-mailadres').set_value(user_admin.ROOT_EMAIL)
        next(w for w in at.text_input if w.label == 'Wachtwoord').set_value('Changed-test-password!')
        next(b for b in at.button if b.label == 'Inloggen').click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any('Beheer' in r.options for r in at.radio))


if __name__ == '__main__':
    unittest.main()
