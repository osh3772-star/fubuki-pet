import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from tools.verify_bundle_icu import repair
class ICURepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.bundle=self.root/'bundle';self.internal=self.bundle/'_internal';self.internal.mkdir(parents=True)
        self.system=self.root/'system';(self.system/'System32').mkdir(parents=True)
        self.candidate=self.internal/'icuuc.dll'
    def pe(self,path,fast_load=False):
        path=Path(path)
        imports=[NS(dll=b'icuuc.dll',imports=[NS(name=b'needed')])] if path.name=='consumer.dll' else []
        names=[b'needed'] if path.parent.name=='System32' else [b'needed_78']
        return NS(DIRECTORY_ENTRY_IMPORT=imports,DIRECTORY_ENTRY_EXPORT=NS(symbols=[NS(name=n) for n in names]),parse_data_directories=lambda **kw:None,close=lambda:None)
    def prepare(self):
        self.candidate.write_bytes(b'original');(self.internal/'consumer.dll').write_bytes(b'consumer')
    def test_absent_candidate_is_noop(self):
        self.assertEqual(repair(self.bundle)['status'],'no_bundled_icu')
    def test_missing_fallback_leaves_candidate(self):
        self.prepare()
        with patch('tools.verify_bundle_icu.pefile.PE',self.pe),patch.dict('os.environ',{'SystemRoot':str(self.system)}):
            with self.assertRaises(RuntimeError):repair(self.bundle)
        self.assertEqual(self.candidate.read_bytes(),b'original')
    def test_verified_fallback_preserves_backup(self):
        self.prepare();(self.system/'System32/icuuc.dll').write_bytes(b'system')
        with patch('tools.verify_bundle_icu.pefile.PE',self.pe),patch.dict('os.environ',{'SystemRoot':str(self.system)}):r=repair(self.bundle)
        self.assertTrue(r['bundle_only']);self.assertFalse(self.candidate.exists())
        self.assertEqual((self.internal/'icuuc.dll.disabled-backup').read_bytes(),b'original')
        self.assertEqual((self.system/'System32/icuuc.dll').read_bytes(),b'system')
    def test_existing_backup_is_not_overwritten(self):
        self.prepare();(self.system/'System32/icuuc.dll').write_bytes(b'system')
        backup=self.internal/'icuuc.dll.disabled-backup';backup.write_bytes(b'keep')
        with patch('tools.verify_bundle_icu.pefile.PE',self.pe),patch.dict('os.environ',{'SystemRoot':str(self.system)}):
            with self.assertRaises(RuntimeError):repair(self.bundle)
        self.assertEqual(backup.read_bytes(),b'keep');self.assertTrue(self.candidate.exists())
