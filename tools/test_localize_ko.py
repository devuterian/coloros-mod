"""Regression tests for the Korean localization's safety boundaries."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import localize_ko as ko


class LocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(ko.read(ko.ROOT / 'localization/ko.json'))

    def test_complete_audit(self):
        self.assertEqual(ko.check(self.data)['untranslated_user_facing_cjk_literals'], 0)

    def test_all_reviewed_pairs_preserve_code(self):
        for source, target in self.data['strings'].items():
            with self.subTest(source=source):
                before = 'val label = ' + json.dumps(source, ensure_ascii=False)
                after = 'val label = ' + json.dumps(target, ensure_ascii=False)
                self.assertEqual(ko.canonical('', before, self.data),
                                 ko.canonical('', after, self.data))

    def test_preference_keys_are_not_translation_targets(self):
        before = 'readBool("statusbar_lyric_enabled", false)'
        after = 'readBool("renamed_key", false)'
        self.assertNotEqual(ko.canonical('', before, self.data),
                            ko.canonical('', after, self.data))

    def test_matching_patterns_are_not_translated(self):
        for values in self.data['preserved_matchers'].values():
            for value in values:
                self.assertNotIn(value, self.data['strings'])

    def test_real_folder_names_remain_unchanged(self):
        path = ko.ROOT / 'app/src/main/java/com/rikumi/colorosmod/MainActivity.kt'
        text = ko.read(path)
        for name in ('Alarms', 'Audiobooks', 'Movies', 'Notifications',
                     'Podcasts', 'Recordings', 'Ringtones'):
            self.assertIn(f'({name})", "{name}")', text)

    def test_apply_is_idempotent(self):
        original_root = ko.ROOT
        with tempfile.TemporaryDirectory() as folder:
            temporary = Path(folder)
            shutil.copytree(original_root / 'app', temporary / 'app',
                            ignore=shutil.ignore_patterns('build'))
            shutil.copy2(original_root / 'LICENSE', temporary / 'LICENSE')
            try:
                ko.ROOT = temporary
                before = {p.relative_to(temporary).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in temporary.rglob('*') if p.is_file()}
                with contextlib.redirect_stdout(io.StringIO()):
                    ko.apply(self.data)
                after = {p.relative_to(temporary).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in temporary.rglob('*') if p.is_file()}
                self.assertEqual(before, after)
                ko.check(self.data)
            finally:
                ko.ROOT = original_root


if __name__ == '__main__':
    unittest.main()
