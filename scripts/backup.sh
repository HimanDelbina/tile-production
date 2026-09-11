#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Tile Production Backup Script
# Creates an atomic PostgreSQL dump and compressed media archive.
# Permissions: backups/ directory 700, files 600.
# ==============================================================================

BACKUP_DIR="backups"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

DB_DUMP_FILE="${BACKUP_DIR}/tileproduction-db-${TIMESTAMP}.dump"
DB_DUMP_TMP="${DB_DUMP_FILE}.tmp"
MEDIA_TAR_FILE="${BACKUP_DIR}/tileproduction-media-${TIMESTAMP}.tar.gz"
MEDIA_TAR_TMP="${MEDIA_TAR_FILE}.tmp"
MANIFEST_FILE="${BACKUP_DIR}/tileproduction-manifest-${TIMESTAMP}.txt"

echo "=== شروع فرآیند پشتیبان‌گیری ($TIMESTAMP) ==="

# 1. PostgreSQL Database Backup (Atomic)
echo "[1/3] در حال پشتیبان‌گیری از پایگاه داده PostgreSQL..."
if ! docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DB_DUMP_TMP"; then
    echo "خطا در تهیه نسخه پشتیبان دیتابیس!" >&2
    rm -f "$DB_DUMP_TMP"
    exit 1
fi

# Verify dump file size is greater than 0
if [ ! -s "$DB_DUMP_TMP" ]; then
    echo "خطا: فایل پشتیبان دیتابیس خالی است!" >&2
    rm -f "$DB_DUMP_TMP"
    exit 1
fi

mv "$DB_DUMP_TMP" "$DB_DUMP_FILE"
chmod 600 "$DB_DUMP_FILE"
echo "✓ دیتابیس با موفقیت ذخیره شد: $DB_DUMP_FILE ($(du -h "$DB_DUMP_FILE" | cut -f1))"

# 2. Media Directory Backup (Atomic)
echo "[2/3] در حال پشتیبان‌گیری از فایل‌های بارگذاری‌شده (Media)..."
MEDIA_BACKED_UP=false

if docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "^web$"; then
    if docker compose exec -T web tar -czf - -C /app media > "$MEDIA_TAR_TMP" 2>/dev/null; then
        if [ -s "$MEDIA_TAR_TMP" ]; then
            mv "$MEDIA_TAR_TMP" "$MEDIA_TAR_FILE"
            chmod 600 "$MEDIA_TAR_FILE"
            MEDIA_BACKED_UP=true
            echo "✓ مدیا از کانتینر web ذخیره شد: $MEDIA_TAR_FILE ($(du -h "$MEDIA_TAR_FILE" | cut -f1))"
        else
            rm -f "$MEDIA_TAR_TMP"
        fi
    fi
fi

if [ "$MEDIA_BACKED_UP" = false ] && [ -d "media" ]; then
    if tar -czf "$MEDIA_TAR_TMP" media 2>/dev/null; then
        if [ -s "$MEDIA_TAR_TMP" ]; then
            mv "$MEDIA_TAR_TMP" "$MEDIA_TAR_FILE"
            chmod 600 "$MEDIA_TAR_FILE"
            MEDIA_BACKED_UP=true
            echo "✓ مدیا از دایرکتوری محلی ذخیره شد: $MEDIA_TAR_FILE ($(du -h "$MEDIA_TAR_FILE" | cut -f1))"
        else
            rm -f "$MEDIA_TAR_TMP"
        fi
    fi
fi

if [ "$MEDIA_BACKED_UP" = false ]; then
    echo "هشدار: پوشه media یا کانتینر مربوطه برای آرشیو مدیا در دسترس نبود."
fi

# 3. Create Manifest
echo "[3/3] در حال ثبت شناسنامه بکاپ..."
{
    echo "Backup Timestamp: $TIMESTAMP"
    echo "Database Dump: $DB_DUMP_FILE"
    if command -v sha256sum >/dev/null 2>&1; then
        echo "DB SHA256: $(sha256sum "$DB_DUMP_FILE" | cut -d' ' -f1)"
        if [ "$MEDIA_BACKED_UP" = true ]; then
            echo "Media Archive: $MEDIA_TAR_FILE"
            echo "Media SHA256: $(sha256sum "$MEDIA_TAR_FILE" | cut -d' ' -f1)"
        fi
    fi
} > "$MANIFEST_FILE"
chmod 600 "$MANIFEST_FILE"

echo "=== پایان موفق پشتیبان‌گیری ==="
echo "خلاصه در $MANIFEST_FILE ذخیره شد."
