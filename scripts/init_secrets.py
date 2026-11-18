"""Generate local secrets once; never overwrite an existing repository password."""
from pathlib import Path
import secrets
root = Path(__file__).resolve().parents[1] / 'secrets'
root.mkdir(exist_ok=True)
for name in ['api_token', 'restic_password']:
    path = root / (name + '.txt')
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32), encoding='ascii')
        path.chmod(0o600)
print('Secrets ready. API token: secrets/api_token.txt. Do not publish this directory.')
