import os
import time
from pathlib import Path
root = Path(os.getenv('SOURCE_DIR', '/source'))
root.mkdir(parents=True, exist_ok=True)
samples = {'clients.csv': 'id,name,department\n1,Demo Client,Sales\n2,Test Client,Support\n',
           'policy.txt': 'Corporate backup demonstration. Synthetic data only.\n',
           'reports/quarter.txt': 'Quarterly revenue: 1250000 RUB. Synthetic example.\n'}
for name, value in samples.items():
    file = root / name
    file.parent.mkdir(parents=True, exist_ok=True)
    if not file.exists():
        file.write_text(value, encoding='utf-8', newline='\n')
(root / '.ready').touch()
print('Synthetic corporate data initialized', flush=True)
while True:
    time.sleep(60)
