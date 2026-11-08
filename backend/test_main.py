import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class APITests(unittest.TestCase):
    def test_health(self):
        self.assertEqual(main.health()['status'], 'ok')

    def test_ten_unique_modules(self):
        self.assertEqual(len(main.MODULES), 10)
        self.assertEqual(len(main.INDEX), 10)

    def test_missing_modules_not_marked_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main, 'PROJECTS_ROOT', Path(temp)):
                self.assertEqual(len(main.modules()), 10)
                self.assertTrue(all(m['status'] == 'missing' for m in main.modules()))

    def test_ready_module_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'json-output-validator'
            folder.mkdir()
            (folder / 'validator.py').write_text('pass', encoding='utf-8')
            with patch.object(main, 'PROJECTS_ROOT', Path(temp)):
                found = {m['id']: m for m in main.modules()}
                self.assertEqual(found['json-output-validator']['status'], 'ready')
                self.assertEqual(found['rag-retrieval-tester']['status'], 'missing')

    def test_summary_only_existing_metrics(self):
        self.assertEqual(main.summary_metrics({'total': 5, 'passed': 2, 'results': [1], 'delta': {'f1': .2}}),
                         {'total': 5, 'passed': 2, 'delta': {'f1': .2}})

    def test_unknown_module_rejected(self):
        with self.assertRaises(Exception) as err:
            main.run_module('not-a-module')
        self.assertEqual(err.exception.status_code, 404)

    def test_subprocess_report_integration(self):
        # Real subprocess execution on a temporary local fixture; no network or Gemini.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            folder = base / 'json-output-validator'
            folder.mkdir()
            (folder / 'validator.py').write_text(
                'import json\nfrom pathlib import Path\nPath("report.json").write_text(json.dumps({"total":2,"passed":1}))\n',
                encoding='utf-8')
            with patch.object(main, 'PROJECTS_ROOT', base), patch.object(main, 'LOG_PATH', base / 'runs.jsonl'), patch.object(main, 'DB_PATH',base/'runs.db'):
                result = main.run_module('json-output-validator')
                self.assertEqual(result['summary']['total'], 2)
                self.assertFalse(result['live_model_evaluated'])
                self.assertEqual(len(main.recent_runs()), 1)


if __name__ == '__main__':
    unittest.main()
