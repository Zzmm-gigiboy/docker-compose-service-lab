#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PYCODE'
from urllib.request import urlopen
for port in (8000, 8001, 8002, 8080):
    url=f'http://127.0.0.1:{port}/health'
    with urlopen(url, timeout=5) as result:
        if result.status != 200: raise SystemExit(f'{url}: HTTP {result.status}')
    print('OK',url)
PYCODE
