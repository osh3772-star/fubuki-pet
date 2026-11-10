import json,tempfile,unittest
from pathlib import Path
from tools.build_program import runtime_files
FONT_FILES = ('NotoSansKR.ttf', 'NotoSansKR-OFL.txt', 'NotoSansJP.ttf', 'NotoSansJP-OFL.txt')
class BuildResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'assets/fonts').mkdir(parents=True); (self.root/'config').mkdir()
        (self.root/'assets/runtime_candidate.json').write_text(json.dumps({'placeholder':'assets/p.png','clips':{'idle':{'frames':['assets/p.png']}}}))
        (self.root/'assets/p.png').write_bytes(b'fixture'); (self.root/'config/default-settings.json').write_text('{}')
        (self.root/'assets/app-icon.ico').write_bytes(b'icon fixture')
        for name in FONT_FILES: (self.root/'assets/fonts'/name).write_bytes(b'fixture')
    def test_fonts_and_licenses_are_included(self):
        names=[p.relative_to(self.root).as_posix() for p in runtime_files(self.root)]
        for name in FONT_FILES: self.assertIn('assets/fonts/'+name,names)
        self.assertEqual(len(names),len(set(names)))
    def test_missing_font_fails_before_build(self):
        (self.root/'assets/fonts/NotoSansKR.ttf').unlink()
        with self.assertRaisesRegex(ValueError,'NotoSansKR.ttf'): runtime_files(self.root)
    def test_app_icon_is_bundled_for_window_and_tray(self):
        names=[p.relative_to(self.root).as_posix() for p in runtime_files(self.root)]
        self.assertIn('assets/app-icon.ico',names)
    def test_missing_app_icon_fails_before_build(self):
        (self.root/'assets/app-icon.ico').unlink()
        with self.assertRaisesRegex(ValueError,'app-icon.ico'): runtime_files(self.root)
    def test_missing_license_fails_before_build(self):
        (self.root/'assets/fonts/NotoSansJP-OFL.txt').unlink()
        with self.assertRaisesRegex(ValueError,'NotoSansJP-OFL.txt'): runtime_files(self.root)
    def test_registry_path_escape_stays_rejected(self):
        (self.root/'assets/runtime_candidate.json').write_text(json.dumps({'placeholder':'../outside.png','clips':{}}))
        with self.assertRaises(ValueError): runtime_files(self.root)
