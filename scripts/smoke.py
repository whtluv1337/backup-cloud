"""End-to-end HTTP test against a running deployment, including restore hashes."""
import argparse
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://127.0.0.1:8080')
    p.add_argument('--token-file', default='secrets/api_token.txt')
    p.add_argument('--output', default='evidence/http-smoke.json')
    args = p.parse_args()
    base = args.url.rstrip('/') + '/api/'
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + Path(args.token_file).read_text().strip()
    def request(method, path, **kwargs):
        r = session.request(method, base + path, timeout=30, **kwargs)
        r.raise_for_status()
        return r
    for _ in range(90):
        try:
            request('GET', 'health')
            break
        except requests.RequestException:
            time.sleep(2)
    else:
        raise RuntimeError('Deployment did not become healthy')
    assert requests.get(base+'status', timeout=10).status_code == 401
    def job(action, snapshot=None):
        j = request('POST', 'jobs', json={'action':action, 'snapshot':snapshot}).json()
        for _ in range(180):
            state = request('GET', 'status').json()
            item = next(x for x in state['jobs'] if x['id']==j['id'])
            if item['status']=='error':
                raise RuntimeError(item['error'])
            if item['status']=='done':
                return item, state
            time.sleep(2)
        raise TimeoutError('Job did not complete')
    backup, status = job('backup')
    snapshot = backup['summary']['snapshot_id']
    restore, _ = job('restore', snapshot)
    raw = request('GET', 'download/'+restore['id']).content
    expected = {'clients.csv':b'id,name,department\n1,Demo Client,Sales\n2,Test Client,Support\n',
                'policy.txt':b'Corporate backup demonstration. Synthetic data only.\n',
                'reports/quarter.txt':b'Quarterly revenue: 1250000 RUB. Synthetic example.\n'}
    hashes = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for relative, content in expected.items():
            names = [n for n in z.namelist() if n.endswith('/'+relative) or n==relative]
            assert len(names)==1, relative
            actual = z.read(names[0])
            assert actual==content, relative
            hashes[relative]=hashlib.sha256(actual).hexdigest()
    job('check')
    result={'status':'passed','url':args.url,'snapshot':snapshot,'restore_job':restore['id'],
            'unauthorized_rejected':True,'restored_sha256':hashes,'full_repository_check':True}
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
