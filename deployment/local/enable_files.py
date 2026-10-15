"""Enable the private HTTP file feature without rotating any existing key."""
import os
from pathlib import Path
import sys
import tempfile


def enable(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077 or path.parent.stat().st_mode & 0o077:
        raise ValueError('Private configuration permissions are required')
    lines = path.read_text().splitlines()
    keys = [line.split('=', 1)[0] for line in lines if line and not line.startswith('#')]
    if len(keys) != len(set(keys)) or not {'PAGDOC_DATABASE_URL','PAGDOC_SECRET_KEY','PAGDOC_ENCRYPTION_KEY'} <= set(keys):
        raise ValueError('Existing private configuration is invalid')
    updated = [line for line in lines if not line.startswith('PAGDOC_BINARY_HTTP_ENABLED=')]
    updated.append('PAGDOC_BINARY_HTTP_ENABLED=1')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            os.chmod(temporary, 0o600)
            output.write('\n'.join(updated) + '\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    enable(Path(sys.argv[1]))
    print('Private HTTP file feature enabled; existing keys retained.')
