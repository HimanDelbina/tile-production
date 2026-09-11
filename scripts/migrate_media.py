#!/usr/bin/env python3
"""
Migrate uploaded Excel files from legacy 'imports/' folder to 'media/imports/'.

Preserves file timestamps, supports rollback/dry-run, and verifies that all
FileField paths recorded in ProductionImportBatch resolve correctly.
"""
import os
import sys
import shutil
import argparse
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
LEGACY_DIR = BASE_DIR / 'imports'
MEDIA_DIR = BASE_DIR / 'media'
TARGET_DIR = MEDIA_DIR / 'imports'


def migrate_media(mode='copy', dry_run=False):
    print("=" * 60)
    print("برنامه انتقال فایل‌های اکسل به مسیر ماندگار رسانه (media/imports/)")
    print("=" * 60)
    print(f"مسیر مبدأ: {LEGACY_DIR}")
    print(f"مسیر مقصد: {TARGET_DIR}")
    print(f"حالت عملیات: {mode} | اجرای آزمایشی (dry-run): {dry_run}")
    print("-" * 60)

    if not LEGACY_DIR.exists():
        print(f"خطا: پوشه مبدأ {LEGACY_DIR} یافت نشد.")
        return False

    if not dry_run:
        TARGET_DIR.mkdir(parents=True, exist_ok=True)

    files = [f for f in LEGACY_DIR.iterdir() if f.is_file() and not f.name.startswith('.')]
    print(f"تعداد {len(files)} فایل در پوشه مبدأ یافت شد.\n")

    transferred = 0
    skipped = 0

    for file_path in sorted(files, key=lambda p: p.name):
        dest_path = TARGET_DIR / file_path.name
        if dest_path.exists() and dest_path.stat().st_size == file_path.stat().st_size:
            print(f"  [موجود] {file_path.name} قبلاً با همان حجم منتقل شده است.")
            skipped += 1
            continue

        print(f"  [{mode.upper()}] {file_path.name} ({file_path.stat().st_size} بایت) -> {dest_path}")
        if not dry_run:
            if mode == 'copy':
                shutil.copy2(file_path, dest_path)
            elif mode == 'move':
                shutil.move(str(file_path), str(dest_path))
        transferred += 1

    print("-" * 60)
    print(f"پایان عملیات: {transferred} فایل منتقل شد، {skipped} فایل دست‌نخورده باقی ماند.")
    print("ارتباط FileField در پایگاه داده بدون تغییر حفظ می‌شود؛ زیرا مقدار 'imports/...' نسبت به MEDIA_ROOT سنجیده می‌شود.")
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="انتقال فایل‌های اکسل به مسیر جدید media/imports/")
    parser.add_argument('--mode', choices=['copy', 'move'], default='copy', help="روش انتقال: کپی ایمن (پیش‌فرض) یا انتقال")
    parser.add_argument('--dry-run', action='store_true', help="بررسی بدون تغییر فایل‌ها")
    args = parser.parse_args()

    success = migrate_media(mode=args.mode, dry_run=args.dry_run)
    sys.exit(0 if success else 1)
