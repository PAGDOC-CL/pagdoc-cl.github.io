#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${PGHOST:?Set private PostgreSQL host}" "${PGUSER:?Set database user}" "${PGDATABASE:?Set database name}"
: "${PAGDOC_BACKUP_DIR:?Use a private destination outside the repository}" "${PAGDOC_BACKUP_PASSPHRASE:?Set an encryption passphrase through a secret store}"
mkdir -p "$PAGDOC_BACKUP_DIR"
backup_file="$PAGDOC_BACKUP_DIR/pagdoc-$(date -u +%Y%m%dT%H%M%S)-$$.dump.enc"
trap 'rm -f "$backup_file.partial"' EXIT
pg_dump --format=custom | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:PAGDOC_BACKUP_PASSPHRASE -out "$backup_file.partial"
mv "$backup_file.partial" "$backup_file"
sha256sum "$backup_file" > "$backup_file.sha256"
printf 'Encrypted backup completed. Verify restoration in an isolated database.\n'
