"""Regression tests use temporary storage only; optional real-file integration."""
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from docx import Document
from PIL import Image
import storage
from access_control import set_actor
from report_export import build_report
from report_import import parse_report, save_import
from docx_safety import repair_cover_anchors, validate_drawing_anchors

TEMPLATE = Path(__file__).parent / 'templates/rapportage_brandveiligheid_template.docx'


class ReportTests(unittest.TestCase):
    def test_export_import_with_cover_and_many_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / 'photo.png'
            Image.new('RGB', (100, 100), 'red').save(photo)
            data = {'complexnaam': 'Test', 'complexnummer': 'TC123', 'photo_voorgevel': str(photo), 'tekeningen_ontvangen': 'wel'}
            findings = [dict(code_group='G', code_number=i+1, finding_type='Maatregel', gebrek=f'Test {i}', maatregel='Herstellen', photo_before=str(photo)) for i in range(80)]
            out = build_report(TEMPLATE, data, findings)
            validate_drawing_anchors(out)
            parsed = parse_report(out)
            self.assertEqual(len(parsed['findings']), 80)
            self.assertEqual(parsed['data']['tekeningen_ontvangen'], 'wel')
            self.assertEqual(parsed['findings'][-1]['gebrek'], 'Test 79')
            self.assertEqual(repair_cover_anchors(out)[1], 0)
            # Reproduce the old missing-wrap failure and prove repair is surgical.
            with ZipFile(io.BytesIO(out)) as z:
                parts = {n: z.read(n) for n in z.namelist()}
            old = parts['word/document.xml'].replace(b'<wp:wrapNone/>', b'', 1)
            buf = io.BytesIO()
            with ZipFile(buf, 'w') as z:
                for n, value in parts.items():
                    z.writestr(n, old if n == 'word/document.xml' else value)
            with self.assertRaises(ValueError):
                validate_drawing_anchors(buf.getvalue())
            fixed, count = repair_cover_anchors(buf.getvalue())
            self.assertEqual(count, 1)
            validate_drawing_anchors(fixed)

    def test_atomic_storage_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(storage, 'DATA_DIR', Path(tmp)), patch.object(storage, 'DB_PATH', Path(tmp) / 'test.db'):
            storage.init_db()
            uid = storage.register_user('Test', 'test@example.test', 'StrongTestPassword123!')
            with storage.connect() as con:
                con.execute("UPDATE users SET role='admin',is_active=1 WHERE id=?", (uid,))
            set_actor(uid, storage.get_user(uid)['session_version'])
            self.addCleanup(set_actor)
            pid = storage.create_project('Test', 'Client', '', '', uid)
            cid = storage.create_complex(pid, 'Complex', 'TC123', '', '', '', uid)
            source = build_report(TEMPLATE, {}, [dict(code_group='X', code_number=7, finding_type='Maatregel', gebrek='Eigen gebrek', discipline='Eigen werksoort')])
            parsed = parse_report(source)
            rid = save_import(parsed, source, cid, 'Import', uid)
            self.assertEqual(storage.list_findings(rid)[0]['code_number'], 7)
            self.assertEqual(storage.load_report(rid)['complex_id'], cid)
            self.assertTrue((Path(tmp) / storage.load_report(rid)['import_original']).exists())
            # Duplicate keys fail midway: no partial report or files may remain.
            parsed['findings'] *= 2
            before = set((Path(tmp) / 'uploads').iterdir())
            with self.assertRaises(Exception):
                save_import(parsed, source, cid, 'Must rollback', uid)
            self.assertEqual(len(storage.list_reports(cid)), 1)
            self.assertEqual(set((Path(tmp) / 'uploads').iterdir()), before)

    def test_invalid_inputs(self):
        for content in (b'not a docx', b''):
            with self.assertRaises(ValueError):
                parse_report(content)
        out = io.BytesIO()
        Document().save(out)
        with self.assertRaises(ValueError):
            parse_report(out.getvalue())


if __name__ == '__main__':
    unittest.main()
