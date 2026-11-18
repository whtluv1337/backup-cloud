import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from pathlib import Path
from common import connection, enqueue, secret


def run_restic(args):
    result = subprocess.run([os.getenv('RESTIC_BIN', 'restic'), '--no-cache', *args],
                            capture_output=True, text=True, timeout=3600)
    if result.returncode:
        raise RuntimeError('restic exit %s: %s' % (result.returncode, result.stderr[-2000:]))
    return result.stdout


def ensure_repository():
    # Exit 10 specifically means that the repository does not exist.
    result = subprocess.run([os.getenv('RESTIC_BIN', 'restic'), '--no-cache', 'cat', 'config'],
                            capture_output=True, text=True, timeout=60)
    if result.returncode == 10:
        run_restic(['init'])
    elif result.returncode:
        raise RuntimeError('Repository unavailable; initialization refused: ' + result.stderr[-1000:])


def refresh(db):
    db.set('snapshots', run_restic(['snapshots', '--json']))


def claim_job(db):
    # Poll atomically without a blocking read: an empty queue is normal, not an error.
    # Check processing first if a prior move succeeded but its response was lost.
    return db.lindex('processing', -1) or db.rpoplpush('queue', 'processing')


def archive_restore(target, destination):
    # Never package symlink targets from a restored corporate directory.
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(target.rglob('*')):
            if file.is_file() and not file.is_symlink():
                archive.write(file, file.relative_to(target).as_posix())


def perform(db, job):
    action = job['action']
    if action == 'backup':
        source = Path(os.getenv('SOURCE_DIR', '/source'))
        if not (source / '.ready').is_file():
            raise RuntimeError('Source has not been initialized')
        result = run_restic(['backup', str(source), '--host', 'corporate-demo', '--tag', 'corporate', '--json'])
        job['summary'] = json.loads(result.strip().splitlines()[-1])
    elif action == 'restore':
        snapshot = job.get('snapshot', '')
        if not re.fullmatch('[a-f0-9]{64}', snapshot):
            raise ValueError('Invalid snapshot')
        root = Path(os.getenv('RESTORE_ROOT', '/restores'))
        target = root / job['id']
        target.mkdir(parents=True, exist_ok=False)
        try:
            source_path = Path(os.getenv('SOURCE_DIR', '/source')).absolute().as_posix().replace(':', '')
            subtree = snapshot + ':/' + source_path.lstrip('/')
            run_restic(['restore', subtree, '--target', str(target), '--verify'])
            archive_restore(target, root / (job['id'] + '.zip'))
        finally:
            shutil.rmtree(target)
    elif action == 'check':
        job['result'] = run_restic(['check', '--read-data'])[-2000:]
    elif action != 'refresh':
        raise ValueError('Unknown action')
    refresh(db)


def main():
    os.environ['RESTIC_PASSWORD'] = secret('RESTIC_PASSWORD')
    db = connection()
    # Exactly one worker replica: recover the interrupted entry before new work.
    while True:
        try:
            db.ping()
            ensure_repository()
            break
        except Exception as error:
            print(str(error), flush=True)
            time.sleep(5)
    refresh(db)
    interval = int(os.getenv('BACKUP_INTERVAL_SECONDS', '3600'))
    last = float(db.get('scheduler:last') or time.time())
    while True:
        try:
            db.set('worker:heartbeat', str(time.time()))
            if interval > 0 and time.time() - last >= interval:
                enqueue(db, 'backup')
                last = time.time()
                db.set('scheduler:last', str(last))
            ident = claim_job(db)
        except (RedisConnectionError, RedisTimeoutError) as error:
            print('Queue temporarily unavailable: ' + str(error), flush=True)
            time.sleep(2)
            continue
        if not ident:
            time.sleep(1)
            continue
        job = json.loads(db.get('job:' + ident))
        if job.get('status') == 'running':
            # No automatic replay of a possibly completed backup after a crash.
            job.update(status='error', error='Worker interrupted; verify repository and retry manually')
        else:
            job.update(status='running', started=time.time())
            db.set('job:' + ident, json.dumps(job))
            try:
                perform(db, job)
                job['status'] = 'done'
            except Exception as error:
                job.update(status='error', error=str(error))
        job['finished'] = time.time()
        with db.pipeline() as p:
            p.set('job:' + ident, json.dumps(job))
            p.lrem('processing', 1, ident)
            p.execute()


if __name__ == '__main__':
    main()
