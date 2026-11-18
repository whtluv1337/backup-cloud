import os
import json
import time
import uuid
from pathlib import Path
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry


def secret(name):
    path = os.getenv(name + '_FILE')
    value = Path(path).read_text().strip() if path else os.getenv(name, '')
    if len(value) < 20:
        raise RuntimeError(name + ' must contain at least 20 characters')
    return value


def connection():
    # Queue moves must not be replayed automatically after an ambiguous response.
    return redis.Redis.from_url(
        os.getenv('REDIS_URL', 'redis://redis:6379/0'), decode_responses=True,
        socket_connect_timeout=5, socket_timeout=15, retry=Retry(NoBackoff(), 0))


def enqueue(db, action, snapshot=None):
    job = dict(id=uuid.uuid4().hex, action=action, snapshot=snapshot,
               status='queued', created=time.time())
    with db.pipeline() as p:
        p.set('job:' + job['id'], json.dumps(job))
        p.lpush('queue', job['id'])
        p.lpush('history', job['id'])
        p.execute()
    return job
