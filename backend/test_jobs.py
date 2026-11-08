import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import main

class JobTests(unittest.TestCase):
    def test_database_created_and_empty_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main,'DB_PATH',Path(temp)/'runs.db'):
                self.assertEqual(main.get_jobs(),[])

    def test_invalid_module_job(self):
        with self.assertRaises(Exception) as err:
            main.create_job({'module_id':'does-not-exist'})
        self.assertEqual(err.exception.status_code,404)

    def test_missing_module_job(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main,'PROJECTS_ROOT',Path(temp)):
                with self.assertRaises(Exception) as err:
                    main.create_job({'module_id':'json-output-validator'})
                self.assertEqual(err.exception.status_code,404)

    def test_job_not_found(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main,'DB_PATH',Path(temp)/'runs.db'):
                with self.assertRaises(Exception) as err:
                    main.get_job('missing')
                self.assertEqual(err.exception.status_code,404)
