"""Actual backup/recovery integration check using only fictitious CI content."""
import importlib.util
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('private_backup', Path(__file__).with_name('backup.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
config = Path(sys.argv[1])
destination = Path(sys.argv[2])
os.umask(0o077)
try:
    output = module.create_backup(config, destination, 'ci-only-fictitious-backup-passphrase')
except module.BackupError as exc:
    # CI contains only fictitious records; do not enable this output for real data.
    print(getattr(exc, 'diagnostic', 'Backup content verification failed'), file=sys.stderr)
    raise
assert output.is_file()
assert output.read_bytes().startswith(module.MAGIC)
assert not list(destination.glob('*.partial'))
assert len(list(destination.glob('*.pagdoc.enc'))) == 1
print('CI backup: authenticated encryption, isolated PostgreSQL restore and document content recovery verified.')
