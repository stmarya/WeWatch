"""LOOPBACK-ONLY platform QA fixture. Never deploy this known-secret test server."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from platform_app import create_app

if not os.getenv('WEWATCH_QA_DIR'):
    raise SystemExit('Set WEWATCH_QA_DIR to an existing private mktemp -d directory')
output = Path(os.environ['WEWATCH_QA_DIR']).absolute()
if not output.is_dir() or output.is_symlink():
    raise SystemExit('QA directory must exist and must not be a symlink')
if os.name != 'nt' and (output.stat().st_uid != os.getuid() or output.stat().st_mode & 0o077):
    raise SystemExit('QA directory must be owned by this user with mode 0700')
app = create_app({'SECRET_KEY': 'phase-one-local-qa-fixture-secret-only',
                  'DATABASE': str(output / 'platform.sqlite3'),
                  'MAIL_DIRECTORY': str(output / 'outbox'),
                  'MAIL_TRANSPORT': 'file', 'PUBLIC_URL': 'http://127.0.0.1:5002',
                  'ENVIRONMENT': 'development', 'RATE_LIMITS_ENABLED': False})
app.run(host='127.0.0.1', port=5002, debug=False, use_reloader=False)
