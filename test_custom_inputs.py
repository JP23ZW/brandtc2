import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import storage
from access_control import set_actor


class CustomInputTests(unittest.TestCase):
    def test_custom_options_and_app_start(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(storage, 'DATA_DIR', Path(tmp)), patch.object(storage, 'DB_PATH', Path(tmp) / 'test.db'):
            storage.init_db()
            uid = storage.register_user('Test', 'ui@example.test', 'StrongTestPassword123!')
            with storage.connect() as con:
                con.execute("UPDATE users SET role='admin',is_active=1 WHERE id=?", (uid,))
            set_actor(uid, storage.get_user(uid)['session_version'])
            self.addCleanup(set_actor)
            pid = storage.create_project('Test', 'Client', '', '', uid)
            cid = storage.create_complex(pid, 'Test', '', '', '', '', uid)
            rid = storage.create_report(cid, 'Test', uid)
            data = storage.load_report(rid)
            data.update(status='Eigen status', woonvorm='Eigen woonvorm')
            storage.save_report(rid, data, uid)
            at = AppTest.from_file(str(Path(__file__).parent / 'app.py'), default_timeout=20)
            at.session_state['user_id'] = uid
            at.session_state['auth_session_version'] = storage.get_user(uid)['session_version']
            at.run()
            self.assertFalse(at.exception)
            for tab in ('Rapportgegevens', 'Algemene gegevens', 'Inspectie', 'Bevindingen'):
                at.session_state['navigate_to'] = tab
                at.run()
                self.assertFalse(at.exception, tab)
                if tab == 'Rapportgegevens':
                    self.assertEqual(next(s for s in at.selectbox if s.label == 'Status').value, 'Eigen status')
                if tab == 'Algemene gegevens':
                    self.assertTrue(any(s.value == 'Eigen woonvorm' for s in at.selectbox))
                if tab == 'Inspectie':
                    combo = next(s for s in at.multiselect if s.label.startswith('Standaard gebreken'))
                    self.assertTrue(combo.proto.accept_new_options)
                    combo.set_value(['Mijn zelf getypte gebrek']).run()
                    self.assertFalse(at.exception)
                    self.assertTrue(any('Mijn zelf getypte gebrek' in t.value for t in at.text_area))


if __name__ == '__main__':
    unittest.main()
