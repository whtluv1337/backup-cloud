import argparse
import re
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--prefix', required=True)
p.add_argument('--tag', required=True)
p.add_argument('--output', default='deploy/kubernetes.generated.yaml')
a = p.parse_args()
if not re.fullmatch(r'[a-z0-9./_-]+', a.prefix) or not re.fullmatch(r'[a-zA-Z0-9_.-]+', a.tag):
    raise SystemExit('Invalid image prefix or tag')
root = Path(__file__).resolve().parents[1]
text = (root/'deploy/kubernetes.template.yaml').read_text()
Path(a.output).write_text(text.replace('IMAGE_PREFIX',a.prefix).replace('IMAGE_TAG',a.tag),encoding='utf-8')
print(a.output)
