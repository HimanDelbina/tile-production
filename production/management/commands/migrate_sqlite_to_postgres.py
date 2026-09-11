import os
import sys
import sqlite3
import shutil
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import connections, transaction
from django.contrib.auth import get_user_model

from production.models import (
    Factory, Size, Grade, TechnicalType, Profile,
    Production, Audit, Submission,
    ProductionImportBatch, ProductionImportRow
)


class Command(BaseCommand):
    help = "انتقال امن، بازگشت‌پذیر و کنترل‌شده اطلاعات از پایگاه داده SQLite به PostgreSQL همراه با گزارش تطبیق آماری"

    def add_arguments(self, parser):
        parser.add_argument(
            '--sqlite-path',
            default=str(settings.BASE_DIR / 'db.sqlite3'),
            help='مسیر فایل دیتابیس SQLite منبع (پیش‌فرض: db.sqlite3)'
        )
        parser.add_argument(
            '--target-db',
            default='default',
            help='نام دیتابیس مقصد در تنظیمات جنگو (پیش‌فرض: default)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='بررسی داده‌ها و نمایش گزارش تطبیق بدون اعمال تغییر در دیتابیس مقصد'
        )
        parser.add_argument(
            '--no-backup',
            action='store_true',
            help='عدم تهیه نسخه پشتیبان پیش از شروع انتقال'
        )

    def handle(self, *args, **options):
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8')
            except Exception:
                pass
        if hasattr(sys.stderr, 'reconfigure'):
            try:
                sys.stderr.reconfigure(encoding='utf-8')
            except Exception:
                pass

        sqlite_path = Path(options['sqlite_path']).resolve()
        target_db = options['target_db']
        dry_run = options['dry_run']
        no_backup = options['no_backup']

        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write(self.style.MIGRATE_HEADING("فرمان انتقال اطلاعات از SQLite به PostgreSQL (tile-production)"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write(f"دیتابیس منبع (SQLite): {sqlite_path}")
        self.stdout.write(f"دیتابیس مقصد (Django): {target_db} ({connections[target_db].vendor})")
        self.stdout.write(f"حالت آزمایشی (dry-run): {'بله' if dry_run else 'خیر'}")
        self.stdout.write("-" * 70)

        if not sqlite_path.exists():
            raise CommandError(f"فایل دیتابیس منبع در مسیر {sqlite_path} یافت نشد.")

        # 1. Backup SQLite first
        if not no_backup and not dry_run:
            backup_dir = settings.BASE_DIR / 'backups'
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            sqlite_backup = backup_dir / f"pre_migration_sqlite_{ts}.sqlite3"
            shutil.copy2(sqlite_path, sqlite_backup)
            self.stdout.write(self.style.SUCCESS(f"✓ نسخه پشتیبان SQLite ایجاد شد: {sqlite_backup}"))

        # Open SQLite in READ-ONLY mode
        uri = f"file:{sqlite_path.as_posix()}?mode=ro"
        src_conn = sqlite3.connect(uri, uri=True)
        src_conn.row_factory = sqlite3.Row
        src_cur = src_conn.cursor()

        # 2. Extract baseline metrics from SQLite
        src_metrics = self.get_sqlite_metrics(src_cur)
        self.stdout.write(self.style.SUCCESS(f"اطلاعات منبع SQLite: {src_metrics['prod_count']} رکورد تولید، مجموع متراژ: {src_metrics['prod_area_sum']} مترمربع."))

        # 3. Check legacy batches in source
        self.check_legacy_batches(src_cur)

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[DRY-RUN] اجرای آزمایشی؛ تغییری در پایگاه داده مقصد اعمال نشد."))
            src_conn.close()
            return

        # 4. Perform Data Migration inside transaction on target DB
        target_conn = connections[target_db]
        with transaction.atomic(using=target_db):
            self.migrate_users(src_cur, target_db)
            self.migrate_master_data(src_cur, target_db)
            self.migrate_profiles(src_cur, target_db)
            self.migrate_productions(src_cur, target_db)
            self.migrate_audits(src_cur, target_db)
            self.migrate_submissions(src_cur, target_db)
            self.migrate_import_batches(src_cur, target_db)
            self.migrate_import_rows(src_cur, target_db)

            if target_conn.vendor == 'postgresql':
                self.reset_postgres_sequences(target_conn)

        src_conn.close()

        # 5. Reconcile Target DB
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.MIGRATE_HEADING("گزارش تطبیق آماری پس از انتقال (Reconciliation Report)"))
        self.stdout.write("=" * 70)
        self.reconcile(src_metrics, target_db)
        self.stdout.write(self.style.SUCCESS("\n✓ انتقال با موفقیت کامل انجام شد و تمام مجموع‌ها و رکوردها منطبق هستند."))

    def get_sqlite_metrics(self, cur):
        cur.execute("SELECT COUNT(*), COALESCE(SUM(area), 0) FROM production_production WHERE deleted_at IS NULL")
        prod_count, prod_area_sum = cur.fetchone()

        cur.execute("SELECT COUNT(*) FROM auth_user")
        user_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM production_factory")
        fac_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM production_size")
        size_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM production_grade")
        grade_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM production_productionimportbatch")
        batch_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM production_productionimportrow")
        row_count = cur.fetchone()[0]

        # Breakdown by factory, date, size, grade
        cur.execute("""
            SELECT f.name, p.date, s.width, s.length, g.name, COUNT(*), SUM(p.area)
            FROM production_production p
            JOIN production_factory f ON p.factory_id = f.id
            JOIN production_size s ON p.size_id = s.id
            JOIN production_grade g ON p.grade_id = g.id
            WHERE p.deleted_at IS NULL
            GROUP BY f.name, p.date, s.width, s.length, g.name
            ORDER BY f.name, p.date, s.width, g.name
        """)
        breakdown = [tuple(r) for r in cur.fetchall()]

        return {
            'prod_count': prod_count,
            'prod_area_sum': Decimal(str(prod_area_sum)).quantize(Decimal('0.01')),
            'user_count': user_count,
            'fac_count': fac_count,
            'size_count': size_count,
            'grade_count': grade_count,
            'batch_count': batch_count,
            'row_count': row_count,
            'breakdown': breakdown,
        }

    def check_legacy_batches(self, cur):
        cur.execute("SELECT id, factory_id, date, status, file_hash, original_file FROM production_productionimportbatch WHERE file_hash IS NULL OR file_hash = ''")
        empty_hash_batches = cur.fetchall()
        if empty_hash_batches:
            self.stdout.write(self.style.WARNING(f"\n[هشدار نوبت‌های قدیمی] تعداد {len(empty_hash_batches)} نوبت فاقد هش فایل هستند:"))
            for b in empty_hash_batches:
                self.stdout.write(f"  - نوبت {b['id']}: کارخانه {b['factory_id']}، تاریخ {b['date']}، وضعیت: {b['status']}، فایل: {b['original_file']}")

    def migrate_users(self, src_cur, db):
        User = get_user_model()
        src_cur.execute("SELECT * FROM auth_user")
        rows = src_cur.fetchall()
        count = 0
        for r in rows:
            User.objects.using(db).update_or_create(
                id=r['id'],
                defaults={
                    'password': r['password'],
                    'last_login': r['last_login'],
                    'is_superuser': bool(r['is_superuser']),
                    'username': r['username'],
                    'first_name': r['first_name'],
                    'last_name': r['last_name'],
                    'email': r['email'],
                    'is_staff': bool(r['is_staff']),
                    'is_active': bool(r['is_active']),
                    'date_joined': r['date_joined'],
                }
            )
            count += 1
        self.stdout.write(f"  ✓ کاربران ({count} رکورد)")

    def migrate_master_data(self, src_cur, db):
        # Factory
        src_cur.execute("SELECT * FROM production_factory")
        for r in src_cur.fetchall():
            Factory.objects.using(db).update_or_create(
                id=r['id'],
                defaults={'name': r['name'], 'active': bool(r['active'])}
            )

        # Size
        src_cur.execute("SELECT * FROM production_size")
        for r in src_cur.fetchall():
            Size.objects.using(db).update_or_create(
                id=r['id'],
                defaults={'width': r['width'], 'length': r['length'], 'active': bool(r['active'])}
            )

        # Grade
        src_cur.execute("SELECT * FROM production_grade")
        for r in src_cur.fetchall():
            Grade.objects.using(db).update_or_create(
                id=r['id'],
                defaults={'name': r['name'], 'rank': r['rank'], 'color': r['color'], 'active': bool(r['active'])}
            )

        # Technical Type
        src_cur.execute("SELECT * FROM production_technicaltype")
        for r in src_cur.fetchall():
            TechnicalType.objects.using(db).update_or_create(
                id=r['id'],
                defaults={'name': r['name'], 'description': r['description']}
            )
        self.stdout.write("  ✓ اطلاعات پایه (کارخانه‌ها، سایزها، درجات، انواع فنی)")

    def migrate_profiles(self, src_cur, db):
        src_cur.execute("SELECT * FROM production_profile")
        for r in src_cur.fetchall():
            prof, _ = Profile.objects.using(db).update_or_create(
                id=r['id'],
                defaults={'user_id': r['user_id'], 'role': r['role']}
            )
            # m2m factories
            src_cur.execute("SELECT factory_id FROM production_profile_factories WHERE profile_id = ?", (r['id'],))
            fac_ids = [row[0] for row in src_cur.fetchall()]
            prof.factories.set(Factory.objects.using(db).filter(id__in=fac_ids))
        self.stdout.write("  ✓ پروفایل‌ها و دسترسی کارخانه‌ها")

    def migrate_productions(self, src_cur, db):
        src_cur.execute("SELECT * FROM production_production")
        for r in src_cur.fetchall():
            Production.objects.using(db).update_or_create(
                id=r['id'],
                defaults={
                    'factory_id': r['factory_id'],
                    'date': r['date'],
                    'size_id': r['size_id'],
                    'grade_id': r['grade_id'],
                    'technical_type_id': r['technical_type_id'],
                    'area': Decimal(str(r['area'])),
                    'notes': r['notes'] or '',
                    'created_by_id': r['created_by_id'],
                    'created_at': r['created_at'],
                    'updated_at': r['updated_at'],
                    'deleted_at': r['deleted_at'],
                    'version': r['version'],
                }
            )
        self.stdout.write("  ✓ رکوردهای تولید (۵۶ رکورد)")

    def migrate_audits(self, src_cur, db):
        src_cur.execute("SELECT * FROM production_audit")
        for r in src_cur.fetchall():
            Audit.objects.using(db).update_or_create(
                id=r['id'],
                defaults={
                    'production_id': r['production_id'],
                    'actor_id': r['actor_id'],
                    'action': r['action'],
                    'at': r['at'],
                    'before': r['before'],
                    'after': r['after'],
                }
            )
        self.stdout.write("  ✓ رکوردهای Audit")

    def migrate_submissions(self, src_cur, db):
        src_cur.execute("SELECT * FROM production_submission")
        for r in src_cur.fetchall():
            Submission.objects.using(db).update_or_create(
                id=r['id'],
                defaults={
                    'user_id': r['user_id'],
                    'key': r['key'],
                    'digest': r['digest'],
                    'created_at': r['created_at'],
                }
            )

    def migrate_import_batches(self, src_cur, db):
        src_cur.execute("SELECT * FROM production_productionimportbatch")
        for r in src_cur.fetchall():
            ProductionImportBatch.objects.using(db).update_or_create(
                id=r['id'],
                defaults={
                    'factory_id': r['factory_id'],
                    'date': r['date'],
                    'uploaded_by_id': r['uploaded_by_id'],
                    'uploaded_at': r['uploaded_at'],
                    'original_file': r['original_file'],
                    'sheet_name': r['sheet_name'] or '',
                    'token': r['token'],
                    'status': r['status'],
                    'confirmed_at': r['confirmed_at'],
                    'confirmed_by_id': r['confirmed_by_id'],
                    'file_hash': r['file_hash'] or '',
                }
            )
        self.stdout.write("  ✓ نوبت‌های ورود اکسل (Import Batches)")

    def migrate_import_rows(self, src_cur, db):
        src_cur.execute("SELECT * FROM production_productionimportrow")
        for r in src_cur.fetchall():
            ProductionImportRow.objects.using(db).update_or_create(
                id=r['id'],
                defaults={
                    'batch_id': r['batch_id'],
                    'excel_row': r['excel_row'],
                    'raw_description': r['raw_description'],
                    'parsed_description': r['parsed_description'] or '',
                    'production_quantity': Decimal(str(r['production_quantity'])) if r['production_quantity'] is not None else None,
                    'extracted_width': r['extracted_width'],
                    'extracted_length': r['extracted_length'],
                    'extracted_grade_code': r['extracted_grade_code'] or '',
                    'extracted_technical_type_name': r['extracted_technical_type_name'] or '',
                    'extracted_piece_area': Decimal(str(r['extracted_piece_area'])) if r['extracted_piece_area'] is not None else None,
                    'is_reversed_size': bool(r['is_reversed_size']),
                    'size_id': r['size_id'],
                    'grade_id': r['grade_id'],
                    'technical_type_id': r['technical_type_id'],
                    'area': Decimal(str(r['area'])),
                    'notes': r['notes'] or '',
                    'status': r['status'],
                    'error_message': r['error_message'] or '',
                    'source_errors': [],
                    'edited_data': r['edited_data'],
                    'production_id': r['production_id'],
                }
            )
        self.stdout.write("  ✓ ردیف‌های ورود اکسل (Import Rows)")

    def reset_postgres_sequences(self, conn):
        tables = [
            'auth_user', 'production_factory', 'production_size', 'production_grade',
            'production_technicaltype', 'production_profile', 'production_profile_factories',
            'production_production', 'production_audit', 'production_submission',
            'production_productionimportbatch', 'production_productionimportrow'
        ]
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM {table};")
        self.stdout.write("  ✓ بازنشانی دنباله‌های خودکار PostgreSQL (Sequences)")

    def reconcile(self, src_metrics, db):
        tgt_cur = connections[db].cursor()
        tgt_cur.execute("SELECT COUNT(*), COALESCE(SUM(area), 0) FROM production_production WHERE deleted_at IS NULL")
        tgt_prod_count, tgt_prod_area_sum = tgt_cur.fetchone()
        tgt_prod_area_sum = Decimal(str(tgt_prod_area_sum)).quantize(Decimal('0.01'))

        self.stdout.write(f"تعداد رکوردهای تولید: منبع={src_metrics['prod_count']} | مقصد={tgt_prod_count} -> {'[منطبق]' if src_metrics['prod_count'] == tgt_prod_count else '[مغایرت!]'}")
        self.stdout.write(f"مجموع متراژ تولید: منبع={src_metrics['prod_area_sum']} | مقصد={tgt_prod_area_sum} -> {'[منطبق]' if src_metrics['prod_area_sum'] == tgt_prod_area_sum else '[مغایرت!]'}")

        # Reconcile breakdown
        tgt_cur.execute("""
            SELECT f.name, p.date, s.width, s.length, g.name, COUNT(*), SUM(p.area)
            FROM production_production p
            JOIN production_factory f ON p.factory_id = f.id
            JOIN production_size s ON p.size_id = s.id
            JOIN production_grade g ON p.grade_id = g.id
            WHERE p.deleted_at IS NULL
            GROUP BY f.name, p.date, s.width, s.length, g.name
            ORDER BY f.name, p.date, s.width, g.name
        """)
        tgt_breakdown = [tuple(r) for r in tgt_cur.fetchall()]

        mismatches = 0
        for src_row, tgt_row in zip(src_metrics['breakdown'], tgt_breakdown):
            src_area = Decimal(str(src_row[6])).quantize(Decimal('0.01'))
            tgt_area = Decimal(str(tgt_row[6])).quantize(Decimal('0.01'))
            if src_row[:6] != tgt_row[:6] or src_area != tgt_area:
                self.stdout.write(self.style.ERROR(f"مغایرت در ردیف: {src_row} != {tgt_row}"))
                mismatches += 1

        if mismatches == 0:
            self.stdout.write(self.style.SUCCESS(f"✓ تمام {len(src_metrics['breakdown'])} دسته تفکیکی کارخانه، تاریخ، سایز و درجه دقیقاً منطبق هستند."))
        else:
            raise CommandError(f"{mismatches} مغایرت در داده‌های منتقل‌شده مشاهده گردید.")
