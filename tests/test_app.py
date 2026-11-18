import os
import sys
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import fakeredis
from api import create_app
from common import enqueue
from worker import perform, ensure_repository, archive_restore, claim_job


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.db = fakeredis.FakeRedis(decode_responses=True)
        self.client = create_app(self.db, 'x' * 32).test_client()
        self.auth = {'Authorization': 'Bearer ' + 'x' * 32}

    def test_auth_and_health(self):
        self.assertEqual(self.client.get('/api/status').status_code, 401)
        self.assertEqual(self.client.get('/api/status', headers={'Authorization':'Bearer неверный'}).status_code, 401)
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        self.assertEqual(self.client.get('/api/status', headers=self.auth).status_code, 200)

    def test_restore_rejects_command_and_path_injection(self):
        for value in ['../../etc/passwd', '; rm -rf /', '--help', 'latest', None]:
            r = self.client.post('/api/jobs', json={'action': 'restore', 'snapshot': value}, headers=self.auth)
            self.assertEqual(r.status_code, 400)
        self.assertEqual(self.db.llen('queue'), 0)

    def test_queue_and_history_are_persisted(self):
        r = self.client.post('/api/jobs', json={'action': 'backup'}, headers=self.auth)
        self.assertEqual(r.status_code, 202)
        ident = r.json['id']
        self.assertEqual(self.db.rpop('queue'), ident)
        self.assertEqual(json.loads(self.db.get('job:' + ident))['status'], 'queued')

    def test_queue_limit(self):
        for _ in range(20):
            enqueue(self.db, 'check')
        self.assertEqual(self.client.post('/api/jobs', json={'action':'backup'}, headers=self.auth).status_code, 429)

    def test_restore_validation_in_worker(self):
        with self.assertRaises(ValueError):
            perform(self.db, {'action':'restore', 'snapshot':'--help'})

    def test_do_not_initialize_on_authentication_failure(self):
        result = type('Result', (), {'returncode':12, 'stderr':'wrong password'})()
        with patch('worker.subprocess.run', return_value=result), patch('worker.run_restic') as run:
            with self.assertRaises(RuntimeError):
                ensure_repository()
            run.assert_not_called()

    def test_zip_relative_paths_and_content(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'restored'
            root.mkdir()
            (root / 'report.txt').write_text('corporate-data', encoding='utf-8')
            target = Path(directory) / 'result.zip'
            archive_restore(root, target)
            with zipfile.ZipFile(target) as z:
                self.assertEqual(z.namelist(), ['report.txt'])
                self.assertEqual(z.read('report.txt'), b'corporate-data')

    def test_download_requires_completed_restore(self):
        r = self.client.get('/api/download/' + 'a'*32, headers=self.auth)
        self.assertEqual(r.status_code, 404)

    def test_idle_queue_returns_promptly_then_accepts_new_job(self):
        started = time.monotonic()
        for _ in range(10):
            self.assertIsNone(claim_job(self.db))
        self.assertLess(time.monotonic() - started, 1)
        job = enqueue(self.db, 'backup')
        self.assertEqual(claim_job(self.db), job['id'])
        self.assertEqual(self.db.llen('queue'), 0)

    def test_existing_processing_entry_precedes_next_job_without_duplication(self):
        first = enqueue(self.db, 'backup')
        second = enqueue(self.db, 'check')
        self.assertEqual(claim_job(self.db), first['id'])
        self.assertEqual(claim_job(self.db), first['id'])
        self.assertEqual(self.db.llen('processing'), 1)
        self.db.lrem('processing', 1, first['id'])
        self.assertEqual(claim_job(self.db), second['id'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
