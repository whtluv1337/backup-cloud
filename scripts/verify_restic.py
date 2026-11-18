"""Real restic round trip; no Docker needed. Uses synthetic temporary data."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def verify(binary='restic', output='evidence/restic-roundtrip.json'):
    started = time.time()
    scratch = Path.cwd() / 'work'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rt-', dir=scratch) as temp:
        root = Path(temp)
        source = root / 'source'
        source.mkdir()
        (source / 'clients.csv').write_text('id,name\n1,Demo Client\n', encoding='utf-8')
        (source / 'policy.txt').write_text('Synthetic corporate policy\n', encoding='utf-8')
        original = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in source.iterdir()}
        env = dict(os.environ, RESTIC_REPOSITORY=str(root/'repo'), RESTIC_PASSWORD='test-password-only-' + os.urandom(12).hex())
        def run(*args, allow=False):
            r = subprocess.run([binary, '--no-cache', *args], env=env, capture_output=True, text=True, timeout=120)
            if not allow and r.returncode:
                raise RuntimeError(r.stderr)
            return r
        version = run('version').stdout.strip()
        missing_code = run('cat', 'config', allow=True).returncode
        run('init')
        run('backup', str(source), '--host', 'test-corporate', '--json')
        snapshots = json.loads(run('snapshots', '--json').stdout)
        first = snapshots[-1]['id']
        (source/'clients.csv').write_text('id,name\n1,Changed Client\n', encoding='utf-8')
        run('backup', str(source), '--host', 'test-corporate', '--json')
        (source/'policy.txt').unlink()
        restore = root/'restored'
        run('restore', first, '--target', str(restore), '--verify')
        restored = {name: hashlib.sha256(next(restore.rglob(name)).read_bytes()).hexdigest() for name in original}
        assert original == restored
        check = run('check', '--read-data')
        wrong = dict(env, RESTIC_PASSWORD='incorrect-password')
        bad = subprocess.run([binary, 'snapshots'], env=wrong, capture_output=True, text=True, timeout=60)
        assert bad.returncode != 0
        result = dict(status='passed', version=version, backend='local temporary repository; not Docker or cloud',
                      missing_repository_exit=missing_code, snapshots_created=2, restored_snapshot=first,
                      sha256_original=original, sha256_restored=restored,
                      deleted_file_restored=True, changed_file_restored=True,
                      wrong_password_rejected=True, repository_check_exit=check.returncode,
                      seconds=round(time.time()-started, 2))
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--binary', default='restic')
    p.add_argument('--output', default='evidence/restic-roundtrip.json')
    a = p.parse_args()
    verify(a.binary, a.output)
