#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Tile Production Restore Script
# Restores PostgreSQL database from a custom-format dump (.dump)
# and extracts media archive (.tar.gz) into the web container or local media dir.
# Usage: ./scripts/restore.sh <path_to_db_dump> [path_to_media_tar] [--yes]
# ==============================================================================

if [ "$#" -lt 1 ]; then
    echo "راهنمای استفاده:"
    echo "  $0 <مسیر_فایل_دیتابیس.dump> [مسیر_فایل_مدیا.tar.gz] [--yes]"
    echo ""
    echo "نسخه‌های پشتیبان موجود:"
    ls -lh backups/*.dump 2>/dev/null || echo "هیچ فایلی در backups/ یافت نشد."
    exit 1
fi

DB_DUMP=""
MEDIA_TAR=""
CONFIRM=false

for arg in "$@"; do
    case "$arg" in
        --yes|-y)
            CONFIRM=true
            ;;
        *.dump)
            DB_DUMP="$arg"
            ;;
        *.tar.gz|*.tgz)
            MEDIA_TAR="$arg"
            ;;
        *)
            if [ -z "$DB_DUMP" ]; then
                DB_DUMP="$arg"
            elif [ -z "$MEDIA_TAR" ]; then
                MEDIA_TAR="$arg"
            fi
            ;;
    esac
done

if [ -z "$DB_DUMP" ] || [ ! -f "$DB_DUMP" ]; then
    echo "خطا: فایل دامپ دیتابیس یافت نشد یا مشخص نشده است: $DB_DUMP" >&2
    exit 1
fi

if [ -n "$MEDIA_TAR" ] && [ ! -f "$MEDIA_TAR" ]; then
    echo "خطا: فایل آرشیو مدیا یافت نشد: $MEDIA_TAR" >&2
    exit 1
fi

echo "=================================================================="
echo "هشدار: عملیات بازگردانی اطلاعات (Restore)"
echo "این عملیات دیتابیس جاری را با داده‌های نسخه پشتیبان زیر جایگزین می‌کند:"
echo "  دیتابیس: $DB_DUMP"
if [ -n "$MEDIA_TAR" ]; then
    echo "  مدیا:    $MEDIA_TAR"
fi
echo "=================================================================="

if [ "$CONFIRM" = false ]; then
    read -r -p "آیا از اجرای عملیات و جایگزینی داده‌ها اطمینان دارید؟ (yes/no): " choice
    if [ "$choice" != "yes" ]; then
        echo "عملیات لغو شد."
        exit 0
    fi
fi

# 1. Restore Database
echo "[1/3] در حال بازنشانی و ایجاد مجدد دیتابیس PostgreSQL..."
docker compose exec -T db sh -c '
    dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB" && \
    createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
'

echo "[2/3] در حال بازگردانی ساختار و اطلاعات از فایل دامپ..."
cat "$DB_DUMP" | docker compose exec -T db sh -c '
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --clean --if-exists 2>/dev/null || \
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges
'

# 2. Restore Media (if provided)
if [ -n "$MEDIA_TAR" ]; then
    echo "[3/3] در حال استخراج فایل‌های مدیا..."
    if docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "^web$"; then
        docker compose exec -T web tar -xzf - -C /app < "$MEDIA_TAR"
        echo "✓ مدیا درون کانتینر web استخراج شد."
    elif [ -d "media" ]; then
        tar -xzf "$MEDIA_TAR"
        echo "✓ مدیا در پوشه محلی media استخراج شد."
    else
        mkdir -p media
        tar -xzf "$MEDIA_TAR" -C .
        echo "✓ پوشه media ایجاد و استخراج شد."
    fi
else
    echo "[3/3] فایل مدیا برای بازگردانی مشخص نشده است (صرف‌نظر شد)."
fi

# 3. Run migrations after restore if web container is running
if docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "^web$"; then
    echo "بررسی مایگریشن‌ها پس از بازگردانی..."
    docker compose exec -T web python manage.py migrate --noinput
fi

echo "=================================================================="
echo "✓ عملیات بازگردانی با موفقیت به پایان رسید."
echo "=================================================================="
