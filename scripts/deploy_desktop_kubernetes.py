"""Deploy the prepared demo to the existing Docker Desktop kind cluster.

Run from the Windows user's terminal, where Docker and kubectl are accessible.
Never prints secret values. Does not change or delete Compose/Swarm data.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = 'docker-desktop'


def run(command, capture=False, data=None, timeout=600):
    result = subprocess.run(command, input=data, capture_output=capture, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode:
        if capture and result.stderr:
            print(result.stderr, file=sys.stderr)
        raise RuntimeError('Command failed: ' + command[0] + ' ' + command[1])
    return result.stdout if capture else ''


def kubectl(*args, **kwargs):
    return run(['kubectl', '--context', CONTEXT, *args], **kwargs)


def load_node_images(images, nodes):
    """Import a platform-specific archive through a temporary node-runtime helper.

    The socket belongs to a Linux kind node, not the Windows host. Helpers have
    no service-account token, do not run dockerd, and are deleted in finally.
    """
    archive = ROOT / '.work' / 'kubernetes-images.tar'
    archive.parent.mkdir(exist_ok=True)
    print('Exporting local images (this can take a few minutes)...', flush=True)
    run(['docker', 'image', 'save', '--platform', 'linux/amd64',
         '--output', str(archive), *images], timeout=1200)
    for node in nodes:
        name = 'backup-image-loader-' + uuid.uuid4().hex[:10]
        helper = {
            'apiVersion':'v1', 'kind':'Pod',
            'metadata':{'name':name, 'namespace':'backupcloud', 'labels':{'purpose':'image-import'}},
            'spec':{
                'nodeName':node, 'restartPolicy':'Never',
                'automountServiceAccountToken':False,
                'tolerations':[{'operator':'Exists'}],
                'containers':[{
                    'name':'importer', 'image':'docker:29-dind',
                    'command':['sh', '-c', 'sleep 3600'],
                    'resources':{'requests':{'cpu':'50m','memory':'64Mi'},
                                 'limits':{'cpu':'1000m','memory':'1Gi'}},
                    'volumeMounts':[{'name':'runtime','mountPath':'/node-containerd.sock'}]
                }],
                'volumes':[{'name':'runtime','hostPath':{
                    'path':'/run/containerd/containerd.sock','type':'Socket'}}]
            }
        }
        try:
            print('Importing images on ' + node + ' ...', flush=True)
            kubectl('apply', '-f', '-', data=json.dumps(helper))
            kubectl('-n', 'backupcloud', 'wait', '--for=condition=Ready',
                    'pod/' + name, '--timeout=240s', timeout=250)
            command = ['kubectl', '--context', CONTEXT, '-n', 'backupcloud',
                       'exec', '-i', name, '--', 'ctr', '--address', '/node-containerd.sock',
                       '--namespace', 'k8s.io', 'images', 'import', '--platform', 'linux/amd64', '-']
            with archive.open('rb') as stream:
                result = subprocess.run(command, stdin=stream, timeout=900)
            if result.returncode:
                raise RuntimeError('Image import failed on ' + node)
        finally:
            kubectl('-n', 'backupcloud', 'delete', 'pod', name,
                    '--ignore-not-found', '--wait=false')
    archive.unlink()


def main():
    os.chdir(ROOT)
    nodes = json.loads(kubectl('get', 'nodes', '-o', 'json', capture=True))['items']
    names = [n['metadata']['name'] for n in nodes]
    expected = {'desktop-control-plane', 'desktop-worker', 'desktop-worker2'}
    if set(names) != expected:
        raise RuntimeError('Unexpected cluster nodes; refusing to deploy: ' + ', '.join(names))
    for node in nodes:
        if not any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']):
            raise RuntimeError('Node not Ready: ' + node['metadata']['name'])
    print('Three nodes are Ready. Checking seven local images...', flush=True)
    images = ['backupcloud/' + name + ':local' for name in ['proxy', 'frontend', 'api', 'worker', 'source']]
    images += ['redis:7.4-alpine', 'restic/rest-server:0.14.0']
    for image in images:
        run(['docker', 'image', 'inspect', image], capture=True)
    print('Assigning one storage node...', flush=True)
    kubectl('label', 'node', 'desktop-worker', 'backup.storage=true', '--overwrite')
    namespace = json.dumps({'apiVersion':'v1', 'kind':'Namespace', 'metadata':{'name':'backupcloud'}})
    kubectl('apply', '-f', '-', data=namespace)
    load_node_images(images, names)
    # Capture the dry-run JSON; do not print or save credentials to an output file.
    secret = kubectl('-n', 'backupcloud', 'create', 'secret', 'generic', 'backup-secrets',
                     '--from-file=api_token=secrets/api_token.txt',
                     '--from-file=restic_password=secrets/restic_password.txt',
                     '--dry-run=client', '-o', 'json', capture=True)
    kubectl('apply', '-f', '-', data=secret)
    template = (ROOT/'deploy/kubernetes.template.yaml').read_text(encoding='utf-8')
    rendered = template.replace('IMAGE_PREFIX', 'backupcloud').replace('IMAGE_TAG', 'local')
    # Every node now has an explicit local copy of the exact image tags.
    docs = list(yaml.safe_load_all(rendered))
    for doc in docs:
        if doc.get('kind') == 'Deployment':
            for container in doc['spec']['template']['spec']['containers']:
                container['imagePullPolicy'] = 'IfNotPresent'
    generated = ROOT/'deploy/kubernetes.desktop.generated.yaml'
    generated.write_text(yaml.safe_dump_all(docs, sort_keys=False), encoding='utf-8')
    print('Applying application resources...', flush=True)
    kubectl('apply', '-f', str(generated))
    # Existing ImagePullBackOff pods may be waiting for a long pull retry interval.
    kubectl('-n', 'backupcloud', 'rollout', 'restart',
            *['deployment/' + n for n in ['source','worker','api','frontend','proxy']])
    for service in ['source', 'redis', 'repository', 'api', 'worker', 'frontend', 'proxy']:
        kubectl('-n', 'backupcloud', 'rollout', 'status', 'deployment/' + service, '--timeout=180s', timeout=200)
    kubectl('-n', 'backupcloud', 'get', 'pods,pvc,svc', '-o', 'wide')
    evidence = ROOT/'evidence'
    evidence.mkdir(exist_ok=True)
    state = kubectl('-n', 'backupcloud', 'get', 'deployments,pods,pvc,services', '-o', 'json', capture=True)
    (evidence/'kubernetes-resources.json').write_text(state, encoding='utf-8')
    print('\nDeployment complete. Next command:')
    print('kubectl --context docker-desktop -n backupcloud port-forward service/proxy 8082:80')
    print('Then open http://127.0.0.1:8082 ; the administrator token is unchanged.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('\nSTOP: ' + str(error), file=sys.stderr)
        sys.exit(1)
