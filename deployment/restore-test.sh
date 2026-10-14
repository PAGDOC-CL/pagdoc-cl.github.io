#!/usr/bin/env bash
set -euo pipefail
: "${PGHOST:?Set isolated PostgreSQL host}" "${PGUSER:?Set database user}" "${PGDATABASE:?Set isolated restore database}" "${PAGDOC_BACKUP_PASSPHRASE:?Set backup passphrase}"
case "$PGDATABASE" in *_restore_test) ;; *) printf 'Blocked: destination database name must end in _restore_test.\n' >&2; exit 1;; esac
backup_file="${1:?Pass encrypted backup path}"
sha256sum --check "$backup_file.sha256"
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:PAGDOC_BACKUP_PASSPHRASE -in "$backup_file" | pg_restore --exit-on-error --no-owner --dbname "$PGDATABASE"
printf 'Restore completed in isolated database. Validate application flows before declaring recovery.\n'
