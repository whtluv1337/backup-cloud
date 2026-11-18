import hmac
import json
import os
import re
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from common import connection, enqueue, secret


def create_app(db=None, token=None):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 4096
    db = db if db is not None else connection()
    token = token or secret('API_TOKEN')

    @app.before_request
    def authenticate():
        if not request.path.startswith('/api/') or request.path == '/api/health':
            return None
        supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(supplied.encode('utf-8'), token.encode('utf-8')):
            return jsonify(error='Требуется токен администратора'), 401

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/api/health')
    def health():
        try:
            db.ping()
            return jsonify(status='ok')
        except Exception:
            return jsonify(status='unavailable'), 503

    @app.get('/api/status')
    def status():
        jobs = [json.loads(x) for ident in db.lrange('history', 0, 49)
                if (x := db.get('job:' + ident))]
        heartbeat = db.get('worker:heartbeat')
        return jsonify(jobs=jobs, snapshots=json.loads(db.get('snapshots') or '[]'),
                       worker_heartbeat=heartbeat)

    @app.post('/api/jobs')
    def jobs():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get('action') not in {'backup', 'restore', 'check', 'refresh'}:
            return jsonify(error='Недопустимая операция'), 400
        snapshot = body.get('snapshot')
        if body['action'] == 'restore' and not (isinstance(snapshot, str) and re.fullmatch('[a-f0-9]{64}', snapshot)):
            return jsonify(error='Требуется полный идентификатор снимка'), 400
        if db.llen('queue') >= 20:
            return jsonify(error='Очередь заполнена'), 429
        return jsonify(enqueue(db, body['action'], snapshot)), 202

    @app.get('/api/download/<ident>')
    def download(ident):
        if not re.fullmatch('[a-f0-9]{32}', ident):
            return jsonify(error='Неверный идентификатор'), 400
        job = json.loads(db.get('job:' + ident) or '{}')
        file = Path(os.getenv('RESTORE_ROOT', '/restores')) / (ident + '.zip')
        if job.get('status') != 'done' or job.get('action') != 'restore' or not file.is_file():
            return jsonify(error='Архив не готов'), 404
        return send_file(file, as_attachment=True, download_name='restore-' + ident + '.zip')

    return app
