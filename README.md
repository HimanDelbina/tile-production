# کاشی‌نگار | سامانه جامع ثبت تولید و گزارش مدیریتی کارخانه‌های کاشی
### Tile Production Management & Reporting System

سیستم یکپارچه، امن و عملیاتی برای ثبت دستی و دسته‌ای تولید روزانه، انطباق هوشمند داده‌های اکسل، گزارش‌گیری چندبُعدی، شاخص‌های کلیدی عملکرد (KPI) و تحلیل ماتریسی خطوط تولید کارخانجات کاشی و سرامیک.

---

## 🌟 ویژگی‌های کلیدی سامانه

- **ثبت چندگانه تولید:**
  - ثبت تکی و چندردیفی دستی با اعتبارسنجی هم‌زمان و جلوگیری از ارسال تکراری (UUID Idempotency).
  - ورود دسته‌ای از طریق فایل اکسل با پیش‌نمایش، اعتبارسنجی یکپارچه، محاسبه «ضریب مساحت واحد تولید» و تشخیص خطاهای فرمولی/منفی.
  - اعمال قانون تغییرناپذیری (Immutability) پس از تایید نهایی نوبت اکسل.
  - دانلود امن و دارای احراز هویت فایل‌های اکسل بارگذاری‌شده بر اساس سطح دسترسی کارخانه‌ها.
- **تقویم و تاریخ شمسی بومی:**
  - پشتیبانی کامل از تاریخ خورشیدی (جلالی)، بدون وابستگی به فرمت‌های غیر استاندارد.
  - محاسبه آغاز هفته از روز شنبه و گروه‌بندی‌های روزانه، ماهانه و سالانه شمسی.
- **داشبورد و گزارش‌های تحلیلی مدیریتی:**
  - نمودارهای بصری روند تولید و ترکیب درجات با رنگ‌بندی یکنواخت.
  - گزارش ماتریسی پویا (تفکیک ابعاد، درجات و سهم ترکیب کیفیت).
  - خروجی استاندارد Excel و گزارش‌های چاپی و PDF (WeasyPrint).
- **تفکیک دسترسی و امنیت شرکتی:**
  - نقش‌های کاربری تفکیک‌شده: **مدیر سامانه**، **کاربر ثبت تولید**، و **مدیر گزارش‌گیر**.
  - محدودسازی کارخانه‌های مجاز به ازای هر کاربر با اعمال در سطح کوئری‌های پایگاه داده.
  - ثبت لاگ کامل تغییرات (Audit Trails) و حذف منطقی (Soft Delete) جهت حفظ یکپارچگی داده‌ها.
- **آماده‌سازی کامل استقرار عملیاتی (Production-Ready):**
  - کانتینرسازی با Docker Compose و جداسازی کامل محیط‌های Dev / Test / Prod.
  - پایگاه داده PostgreSQL 16 به همراه قفل سطری تراکنش‌ها و جلوگیری از Race Condition.
  - اجرای سرویس وب با سرور WSGI قدرتمند Gunicorn و کاربر غیر روت (`tileapp`).
  - سرو فایل‌های استاتیک فشرده و هش‌شده با WhiteNoise.
  - اسکریپت‌های اتمیک پشتیبان‌گیری و بازگردانی دیتابیس و فایل‌های مدیا (`scripts/backup.sh`, `scripts/restore.sh`).
  - دستور اختصاصی مهاجرت اطلاعات از SQLite به PostgreSQL با تنظیم خودکار Sequences.

---

## 🏗️ پشته فناوری (Technology Stack)

| بخش | ابزار و کتابخانه‌ها |
| :--- | :--- |
| **Backend** | Python 3.12, Django 5.x |
| **Database** | PostgreSQL 16 (با ولوم داده ماندگار) |
| **WSGI / App Server** | Gunicorn (Workers: 3, Timeout: 120s) |
| **Static & Media** | WhiteNoise (CompressedManifest), Local Media Volume |
| **Reverse Proxy** | Nginx / Nginx Proxy Manager (پشتیبانی از SSL و هدرهای استاندارد) |
| **Reporting & Export** | openpyxl, WeasyPrint, Chart.js, Jalali Engine |
| **UI & Typography** | فارسی راست‌به‌چپ (RTL)، فونت استاندارد وزیرمتن (Vazirmatn) |

---

## 🚀 راه‌اندازی سریع با Docker Compose

### ۱. پیش‌نیازها
* لینوکس (Ubuntu 22.04 / 24.04 یا Debian 12)
* Docker Engine 24+ و Docker Compose V2

### ۲. دریافت پروژه و تنظیم متغیرها
```bash
git clone https://github.com/HimanDelbina/tile-production.git
cd tile-production

# ایجاد فایل متغیرهای محیطی از روی نمونه
cp .env.example .env
chmod 600 .env
```

فایل `.env` را باز کرده و حداقل موارد زیر را مقداردهی کنید:
```ini
DJANGO_ENV=production
DJANGO_SECRET_KEY=یک_کلید_تصادفی_و_امن_با_حداقل_۵۰_کاراکتر
DJANGO_ALLOWED_HOSTS=tile.yourdomain.ir,127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://tile.yourdomain.ir
DJANGO_COOKIE_SECURE=1
DJANGO_TRUST_PROXY=1
POSTGRES_DB=tileproduction
POSTGRES_USER=tileapp
POSTGRES_PASSWORD=رمز_عبور_بسیار_قوی_پایگاه_داده
```

### ۳. بیلد و اجرای سرویس‌ها
```bash
# ساخت ایمیج و اجرای کانتینرها در پس‌زمینه
docker compose build
docker compose up -d

# مشاهده وضعیت سلامت کانتینرها
docker compose ps
```

### ۴. ایجاد کاربر مدیر ارشد (Superuser)
```bash
docker compose exec -it web python manage.py createsuperuser
```

### ۵. بارگذاری داده‌های پایه اولیه (اختیاری برای نصب خام)
```bash
docker compose exec web python manage.py setup_basics
```

---

## 🔄 مهاجرت داده‌ها از SQLite به PostgreSQL

اگر دیتابیس نسخه قبلی SQLite (شامل رکوردهای تولید، کاربران و فایل‌ها) را در اختیار دارید:

1. فایل `db.sqlite3` را در پوشه ریشه پروژه کپی کنید.
2. اجرای آزمایشی و ارزیابی داده‌ها:
   ```bash
   docker compose exec web python manage.py migrate_sqlite_to_postgres --dry-run
   ```
3. اعمال قطعی مهاجرت (همراه با کپی مدیا و ریست خودکار شناسه جداول PostgreSQL):
   ```bash
   docker compose exec web python manage.py migrate_sqlite_to_postgres
   ```

---

## 💾 پشتیبان‌گیری و بازگردانی (Backup & Restore)

### تهیه نسخه پشتیبان اتمیک:
```bash
chmod +x scripts/*.sh
./scripts/backup.sh
```
این اسکریپت یک نسخه پشتیبان کامل از دیتابیس (`.dump`) و آرشیو فایل‌های رسانه (`.tar.gz`) با کد کنترل یکپارچگی SHA256 در پوشه `backups/` ایجاد می‌کند (با سطح دسترسی امنیتی 700 برای پوشه و 600 برای فایل‌ها).

### بازگردانی اطلاعات:
```bash
./scripts/restore.sh backups/tileproduction-db-YYYYMMDDTHHMMSSZ.dump backups/tileproduction-media-YYYYMMDDTHHMMSSZ.tar.gz
```

---

## 📖 مستندات تکمیلی

- **[راهنمای جامع استقرار روی سرور لینوکس (Host Nginx و NPM)](docs/DEPLOYMENT_GUIDE.fa.md)**
- **[سند فنی اعتبارسنجی فایل‌های اکسل ورودی](docs/VALIDATION.fa.md)**
- **[نمونه کانفیگ Nginx با SSL و محدودیت بادی](docs/nginx.conf.example)**

---

## 🧪 اجرای آزمون‌ها (Testing)

اجرای آزمون‌های واحد و تست‌های رگرسیون جنگو:
```bash
python manage.py test --settings=config.test_settings
```

---

## 📜 مجوز (License)

توسعه‌یافته برای مدیریت خطوط تولید کاشی و سرامیک. کلیه حقوق محفوظ است.
