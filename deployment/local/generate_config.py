"""Create local-only runtime secrets outside Git without overwriting existing keys."""
import base64
import os
from pathlib import Path
import secrets
import sys


def create_config(path: Path) -> bool:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_mode & 0o077:
        raise ValueError('Configuration directory must be private (mode 700)')
    if path.exists():
        if not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError('Existing configuration must be a private file (mode 600)')
        return False
    password = secrets.token_hex(32)
    values = {
        'PAGDOC_POSTGRES_PASSWORD': password,
        'PAGDOC_DATABASE_URL': 'postgresql+psycopg://pagdoc:' + password + '@database:5432/pagdoc',
        'PAGDOC_SECRET_KEY': secrets.token_hex(48),
        'PAGDOC_ENCRYPTION_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode(),
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(''.join(key + '=' + value + '\n' for key, value in values.items()))
    return True


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) == 2 else Path.home()/'.config/pagdoc-private/runtime.env'
    created = create_config(target)
    print('Private configuration created.' if created else 'Existing private configuration retained.')
