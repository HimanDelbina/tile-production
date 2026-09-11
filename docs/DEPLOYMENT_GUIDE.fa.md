# راهنمای جامع استقرار عملیاتی سامانه تولید کاشی (Tile Production)

این مستند، راهنمای گام‌به‌گام، امن و استاندارد جهت استقرار، مهاجرت اطلاعات، نگهداری و پشتیبان‌گیری سامانه ثبت و مدیریت تولید کاشی بر روی سرور لینوکس (Ubuntu 22.04/24.04 LTS یا Debian 12) با استفاده از **Docker Compose**، **PostgreSQL** و **پروکسی معکوس (Nginx یا Nginx Proxy Manager)** می‌باشد.

---

## فهرست مطالب

1. [پیش‌نیازهای سرور لینوکس و ساختار فایل‌ها](#۱-پیش‌نیازهای-سرور-لینوکس-و-ساختار-فایل‌ها)
2. [پیکربندی متغیرهای محیطی (.env)](#۲-پیکربندی-متغیرهای-محیطی-env)
3. [پیکربندی وب‌سرور و پروکسی معکوس](#۳-پیکربندی-وب‌سرور-و-پروکسی-معکوس)
   - [سناریوی الف: استفاده از Nginx نصب‌شده روی سیستم‌عامل میزبان (Host Nginx)](#سناریوی-الف-استفاده-از-nginx-نصب‌شده-روی-سیستم‌عامل-میزبان-host-nginx)
   - [سناریوی ب: استفاده از Nginx Proxy Manager (کانتینری)](#سناریوی-ب-استفاده-از-nginx-proxy-manager-کانتینری)
4. [راه‌اندازی گام‌به‌گام با Docker Compose](#۴-راه‌اندازی-گام‌به‌گام-با-docker-compose)
5. [مهاجرت اطلاعات از پایگاه داده SQLite به PostgreSQL](#۵-مهاجرت-اطلاعات-از-پایگاه-داده-sqlite-به-postgresql)
6. [ایجاد حساب مدیر ارشد (Superuser)](#۶-ایجاد-حساب-مدیر-ارشد-superuser)
7. [راهنمای پشتیبان‌گیری و بازگردانی اطلاعات (Backup & Restore)](#۷-راهنمای-پشتیبان‌گیری-و-بازگردانی-اطلاعات-backup--restore)
8. [فرآیند به‌روزرسانی کد و اعمال تغییرات (Updates)](#۸-فرآیند-به‌روزرسانی-کد-و-اعمال-تغییرات-updates)
9. [چک‌لیست تحویل و تفکیک اقدامات](#۹-چک‌لیست-تحویل-و-تفکیک-اقدامات)

---

## ۱. پیش‌نیازهای سرور لینوکس و ساختار فایل‌ها

### الف) حداقل منابع سخت‌افزاری پیشنهادی
* **پردازنده (CPU):** حداقل ۲ هسته
* **حافظه اصلی (RAM):** حداقل ۲ گیگابایت (پیشنهادی ۴ گیگابایت)
* **فضای دیسک (Storage):** حداقل ۲۰ گیگابایت SSD/NVMe (متناسب با حجم فایل‌های اکسل بارگذاری‌شده)

### ب) بسته‌های نرم‌افزاری مورد نیاز
ابتدا بسته‌های سیستم‌عامل را به‌روزرسانی کرده و Docker و Docker Compose را نصب کنید:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git ufw fail2ban

# نصب Docker Engine و Docker Compose V2 رسمی
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker
```

### ج) تنظیم دیوار آتش (UFW)
تنها پورت‌های ضروری را باز بگذارید:
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh comment 'SSH Port'
sudo ufw allow 80/tcp comment 'HTTP Web'
sudo ufw allow 443/tcp comment 'HTTPS Web'
sudo ufw enable
```

### د) ساختار دایرکتوری استقرار
توصیه می‌شود پروژه در مسیر استاندارد زیر مستقر گردد:
```
/opt/tile-production/
├── compose.yaml
├── Dockerfile
├── .dockerignore
├── .env.example
├── .env                          # فایل حاوی مقادیر محرمانه (عدم انتشار در گیت)
├── config/
├── production/
├── static/
├── templates/
├── scripts/
│   ├── backup.sh
│   ├── restore.sh
│   └── test-postgres.sh
├── docs/
└── backups/                      # ذخیره فایل‌های پشتیبان با دسترسی محدود 700
```

---

## ۲. پیکربندی متغیرهای محیطی (.env)

فایل نمونه `.env.example` را به عنوان فایل اجرایی `.env` کپی کنید:
```bash
cp .env.example .env
chmod 600 .env
```

سپس فایل `.env` را با ویرایشگر باز کرده و مقادیر زیر را با دقت و به‌صورت امن مقداردهی کنید:

1. **کلید امنیتی (`DJANGO_SECRET_KEY`):**  
   یک رشته تصادفی و قدرتمند با حداقل ۵۰ کاراکتر تولید کنید:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(50))"
   ```
   مقدار خروجی را در `DJANGO_SECRET_KEY` قرار دهید.

2. **محیط و اشکال‌زدایی:**
   ```ini
   DJANGO_ENV=production
   DJANGO_DEBUG=0
   ```

3. **دامنه‌ها و مبداهای مجاز (`ALLOWED_HOSTS` و `CSRF_TRUSTED_ORIGINS`):**
   ```ini
   DJANGO_ALLOWED_HOSTS=tile.yourdomain.ir,www.tile.yourdomain.ir
   DJANGO_CSRF_TRUSTED_ORIGINS=https://tile.yourdomain.ir,https://www.tile.yourdomain.ir
   ```

4. **امنیت کوکی و پروکسی:**
   ```ini
   DJANGO_COOKIE_SECURE=1
   DJANGO_TRUST_PROXY=1
   DJANGO_SSL_REDIRECT=0
   DJANGO_HSTS_SECONDS=0
   ```
   > **نکته بسیار مهم درباره `DJANGO_SSL_REDIRECT`:**  
   > از آنجا که هدایت ترافیک HTTP به HTTPS توسط وب‌سرور یا پروکسی معکوس (Nginx) انجام می‌شود، مقدار `DJANGO_SSL_REDIRECT` را برابر `0` بگذارید تا از ایجاد **Redirect Loop (حلقه هدایت نامتناهی)** جلوگیری شود.  
   > مقدار `DJANGO_TRUST_PROXY=1` باعث فعال‌سازی `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` در جنگو شده و وضعیت امن پروتکل را به درستی تشخیص می‌دهد.

5. **اطلاعات پایگاه داده PostgreSQL:**
   یک رمز عبور قوی برای دیتابیس تعیین کنید:
   ```ini
   POSTGRES_DB=tileproduction
   POSTGRES_USER=tileapp
   POSTGRES_PASSWORD=رمز_عبور_بسیار_قوی_و_تصادفی
   POSTGRES_HOST=db
   POSTGRES_PORT=5432
   ```

---

## ۳. پیکربندی وب‌سرور و پروکسی معکوس

### سناریوی الف: استفاده از Nginx نصب‌شده روی سیستم‌عامل میزبان (Host Nginx)

در این سناریو، سرویس جنگو پورت `8000` را روی لوکال‌هاست سرور (`127.0.0.1:8000`) اکسپوز می‌کند و Nginx میزبان به عنوان پروکسی معکوس و پایان‌دهنده SSL (Terminator) عمل می‌کند.

1. نصب Nginx و Certbot:
   ```bash
   sudo apt install -y nginx certbot python3-certbot-nginx
   ```

2. دریافت گواهی رایگان SSL از Let's Encrypt:
   ```bash
   sudo certbot certonly --nginx -d tile.yourdomain.ir
   ```

3. ایجاد فایل کانفیگ در `/etc/nginx/sites-available/tile-production`:
   ```nginx
   # هدایت کلیه ترافیک HTTP به HTTPS
   server {
       listen 80;
       listen [::]:80;
       server_name tile.yourdomain.ir;

       return 301 https://$host$request_uri;
   }

   # ترافیک امن HTTPS
   server {
       listen 443 ssl http2;
       listen [::]:443 ssl http2;
       server_name tile.yourdomain.ir;

       # گواهی‌نامه‌های SSL
       ssl_certificate /etc/letsencrypt/live/tile.yourdomain.ir/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/tile.yourdomain.ir/privkey.pem;
       ssl_protocols TLSv1.2 TLSv1.3;
       ssl_ciphers HIGH:!aNULL:!MD5;

       # سقف مجاز بارگذاری اکسل (متناسب با فایل‌های اکسل بزرگ تا ۱۰ مگابایت + اورهد)
       client_max_body_size 15m;

       # زمان انقضای پاسخ‌دهی برای بارگذاری و پردازش فایل‌های بزرگ
       proxy_read_timeout 180s;
       proxy_connect_timeout 60s;
       proxy_send_timeout 180s;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_set_header X-Forwarded-Host $host;
           proxy_set_header X-Forwarded-Port $server_port;
       }
   }
   ```

4. فعال‌سازی تنظیمات و ری‌استارت Nginx:
   ```bash
   sudo ln -sf /etc/nginx/sites-available/tile-production /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl reload nginx
   ```

---

### سناریوی ب: استفاده از Nginx Proxy Manager (کانتینری)

اگر در سرور خود از کانتینر Nginx Proxy Manager (NPM) برای مدیریت ترافیک و گواهی‌ها استفاده می‌کنید:

1. **نکته کلیدی شبکه:** کانتینر NPM نباید از طریق `localhost` به سرویس جنگو متصل شود؛ زیرا داخل کانتینر، `localhost` به خود همان کانتینر اشاره دارد. اتصال باید از طریق یک شبکه داکر مشترک (`docker network`) و نام سرویس (`web`) انجام گیرد.

2. **تعریف شبکه مشترک داکر (Shared Network):**  
   یک شبکه داکر با نام مثلاً `proxy-net` بسازید:
   ```bash
   docker network create proxy-net
   ```

3. اتصال Nginx Proxy Manager به این شبکه:  
   در `compose.yaml` مربوط به NPM، شبکه `proxy-net` را به سرویس NPM متصل کنید:
   ```yaml
   networks:
     default:
     proxy-net:
       external: true
   ```

4. اتصال پروژه Tile Production به شبکه مشترک:  
   در فایل `compose.yaml` پروژه، شبکه خارجی `proxy-net` را تعریف کرده و سرویس `web` را عضو آن نمایید:
   ```yaml
   services:
     web:
       # ... سایر تنظیمات
       networks:
         - default
         - proxy-net

   networks:
     default:
       internal: false
     proxy-net:
       external: true
   ```

5. **تنظیم در پنل وب Nginx Proxy Manager:**
   - وارد پنل کاربری NPM شوید و یک **Proxy Host** جدید اضافه کنید:
     - **Domain Names:** `tile.yourdomain.ir`
     - **Scheme:** `http`
     - **Forward Hostname / IP:** `web` (نام سرویس کانتینر در compose.yaml)
     - **Forward Port:** `8000`
     - **Block Common Exploits:** فعال (ON)
     - **Websockets Support:** فعال (اختیاری)
   - در تب **SSL**:
     - گواهی Let's Encrypt انتخاب یا ایجاد شود.
     - **Force SSL:** فعال (ON)
     - **HTTP/2 Support:** فعال (ON)
   - در تب **Advanced** (Custom Nginx Configuration):  
     برای پشتیبانی از بارگذاری فایل‌های اکسل، دستور زیر را وارد کنید:
     ```nginx
     client_max_body_size 15m;
     proxy_read_timeout 180s;
     ```

---

## ۴. راه‌اندازی گام‌به‌گام با Docker Compose

پس از تنظیم `.env` و کانفیگ شبکه/پروکسی، سرویس‌ها را بالا بیاورید:

```bash
cd /opt/tile-production

# ۱. بیلد ایمیج برنامه (شامل جمع‌آوری استاتیک با WhiteNoise و کاربر امن غیر روت tileapp)
docker compose build

# ۲. راه‌اندازی کانتینرها در پس‌زمینه
docker compose up -d

# ۳. بررسی وضعیت کانتینرها و سرویس سلامت‌سنجی
docker compose ps
```

برای مشاهده لاگ‌های وب و دیتابیس:
```bash
docker compose logs -f web
docker compose logs -f db
```

---

## ۵. مهاجرت اطلاعات از پایگاه داده SQLite به PostgreSQL

پروژه شامل ابزار اختصاصی و خودکار `migrate_sqlite_to_postgres` است که عملیات انتقال داده‌ها، تبدیل فرمت‌ها، انتقال فایل‌های اکسل و هماهنگ‌سازی Sequenceهای PostgreSQL را انجام می‌دهد.

### مراحل انتقال:

1. **انتقال فایل دیتابیس قبلی:**  
   فایل پایگاه داده SQLite قبلی (مثلاً `db.sqlite3` که شامل ۵۶ رکورد تولید و اطلاعات پایه‌ای است) را به دایرکتوری ریشه پروژه یا مسیر دلخواه انتقال دهید:
   ```bash
   # فرض: فایل db.sqlite3 در مسیر ریشه قرار دارد
   ls -la db.sqlite3
   ```

2. **اجرای آزمایشی بدون تغییر (Dry-Run):**  
   ابتدا برای اطمینان از سلامت ساختار داده‌ها و انطباق آمار، دستور را به صورت آزمایشی اجرا کنید:
   ```bash
   docker compose exec web python manage.py migrate_sqlite_to_postgres --dry-run
   ```
   خروجی باید تعداد ۵۶ رکورد تولید، مجموع متراژ ۳۱,۹۹۲.۰۰ مترمربع، کارخانه‌ها و کاربران را نمایش دهد.

3. **اجرای نهایی مهاجرت اطلاعات:**  
   برای اعمال قطعی داده‌ها در پایگاه داده PostgreSQL:
   ```bash
   docker compose exec web python manage.py migrate_sqlite_to_postgres
   ```

   این دستور به صورت خودکار:
   - یک نسخه پشتیبان تاریخ‌دار از فایل SQLite تهیه می‌کند (`backups/pre_migration_sqlite_*.sqlite3`).
   - جداول پایه‌ای (کارخانه‌ها، ابعاد، درجات، انواع فنی) را وارد می‌کند.
   - حساب‌های کاربری و پروفایل‌ها را همگام‌سازی می‌کند.
   - رکوردهای تولید (`Production`)، لاگ‌های تغییرات (`Audit`) و تاریخچه‌ها را انتقال می‌دهد.
   - نوبت‌های بارگذاری اکسل (`ProductionImportBatch`) و ردیف‌های آن‌ها (`ProductionImportRow`) را ثبت می‌کند.
   - فایل‌های فیزیکی را از پوشه قدیمی به حجم ماندگار رسانه (`media_data:/app/media/imports`) منتقل کرده و هش sha256 آنها را محاسبه و ذخیره می‌کند.
   - **دنباله‌های خودکار PostgreSQL (ID Sequences)** را بر روی بزرگترین شناسه موجود تنظیم می‌کند تا در ثبت‌های بعدی با خطای `IntegrityError (duplicate key)` مواجه نشوید.
   - گزارش نهایی تطبیق آماری را چاپ می‌کند.

---

## ۶. ایجاد حساب مدیر ارشد (Superuser)

برای ایجاد حساب کاربری مدیر بدون افشای رمز عبور در اسکریپت‌ها یا تاریخچه ترمینال:

```bash
docker compose exec -it web python manage.py createsuperuser
```
سامانه از شما نام کاربری، ایمیل و رمز عبور را به صورت محرمانه در ترمینال دریافت کرده و مدیر ارشد جدید را می‌سازد.

---

## ۷. راهنمای پشتیبان‌گیری و بازگردانی اطلاعات (Backup & Restore)

پروژه به اسکریپت‌های بهینه‌سازی‌شده و ایمن مجهز است:

### الف) تهیه نسخه پشتیبان (Backup)
اسکریپت `scripts/backup.sh` یک نسخه پشتیبان فشرده و امن از دیتابیس PostgreSQL (با فرمت custom اتمیک) و یک فایل آرشیو فشرده از دایرکتوری `media` ایجاد کرده و مجوز دسترسی فایل‌ها را روی `600` و پوشه را روی `700` قرار می‌دهد:

```bash
chmod +x scripts/backup.sh scripts/restore.sh
./scripts/backup.sh
```

فایل‌های تولیدشده در پوشه `backups/`:
- `tileproduction-db-YYYYMMDDTHHMMSSZ.dump` (فایل باینری دامپ دیتابیس)
- `tileproduction-media-YYYYMMDDTHHMMSSZ.tar.gz` (آرشیو فایل‌های اکسل بارگذاری‌شده)
- `tileproduction-manifest-YYYYMMDDTHHMMSSZ.txt` (شناسنامه و کدهای کنترلی SHA256)

#### تنظیم زمان‌بندی خودکار پشتیبان‌گیری با Crontab:
برای تهیه پشتیبان خودکار شبانه در ساعت ۰۲:۳۰ بامداد:
```bash
crontab -e
```
خط زیر را اضافه کنید:
```cron
30 2 * * * cd /opt/tile-production && ./scripts/backup.sh >> /var/log/tile-backup.log 2>&1
```

### ب) بازگردانی اطلاعات (Restore)
در صورت نیاز به بازگردانی کامل سامانه بر روی سرور یا بازیابی پس از سانحه:

```bash
# ساختار: ./scripts/restore.sh <فایل_دامپ_دیتابیس> [فایل_آرشیو_مدیا] [--yes]
./scripts/restore.sh backups/tileproduction-db-20260911T120000Z.dump backups/tileproduction-media-20260911T120000Z.tar.gz
```
این اسکریپت ابتدا از شما تاییدیه می‌گیرد، دیتابیس را بازنشانی کرده و اطلاعات و فایل‌های مدیا را درون کانتینر بازیابی می‌کند.

---

## ۸. فرآیند به‌روزرسانی کد و اعمال تغییرات (Updates)

برای دریافت نسخه‌های جدید کد و به‌روزرسانی بدون اختلال:

```bash
cd /opt/tile-production

# ۱. تهیه پشتیبان پیش از اعمال هرگونه تغییر
./scripts/backup.sh

# ۲. دریافت تغییرات کد از مخزن گیت
git pull origin main

# ۳. بازسازی ایمیج و ری‌استارت سرویس‌ها
docker compose build web
docker compose up -d web

# ۴. اجرای مایگریشن‌های دیتابیس در صورت وجود
docker compose exec web python manage.py migrate --noinput
```

---

## ۹. چک‌لیست تحویل و تفکیک اقدامات

### اقدامات انجام‌شده در سورس پروژه (کامل و راستی‌آزمایی‌شده):
- [x] رفع باگ A (تکرار رکوردها در تأیید همزمان نوبت‌های یکسان) با قفل سطری و ایجاد قید یکتایی دیتابیس `unique_confirmed_import_batch`.
- [x] رفع باگ B (تغییر وضعیت ردیف متراژ منفی به ok بعد از بازپردازش) با لایه اعتبارسنجی یکپارچه و نگهداری خطاهای اولیه (`source_errors`).
- [x] رفع باگ C (امکان تغییر مقادیر ردیف‌های پیش‌نمایش پس از تأیید نوبت) با غیرقابل تغییر کردن نوبت‌های تایید شده در بک‌اند و فرانت‌اند.
- [x] بازنویسی تست‌های رگرسیون برای تضمین عدم بازگشت باگ‌ها (۷۴ تست موفق).
- [x] جداسازی دقیق تنظیمات (`settings.py` و `test_settings.py`) و قطع خودکار برنامه در صورت عدم وجود PostgreSQL در پروداکشن.
- [x] اضافه کردن دانلود امن و دارای احراز هویت فایل‌های اکسل بارگذاری‌شده بر اساس سطح دسترسی کارخانه.
- [x] تغییر اصطلاحات فنی به «ضریب مساحت واحد تولید» بدون تغییر ماهیت متراژ کل.
- [x] پیکربندی Dockerfile با ساختار چندمرحله‌ای، کاربر غیر روت `tileapp` و ذخیره‌سازی داده‌های مدیا در volume مستقل.
- [x] آماده‌سازی اسکریپت‌های اتمیک پشتیبان‌گیری و بازگردانی همراه با آرشیو مدیا.
- [x] توسعه دستور هوشمند `migrate_sqlite_to_postgres` همراه با ریست خودکار دنباله‌های کلید اصلی.

### اقدامات الزامی که باید توسط مدیر سرور روی سرور لینوکس نهایی انجام شود:
1. ایجاد فایل واقعی `.env` بر اساس `.env.example` و تنظیم کلید امنیتی ۵۰ کاراکتری تصادفی و رمز دیتابیس.
2. پیکربندی دامنه در DNS و اتصال به IP عمومی سرور.
3. راه‌اندازی پروکسی معکوس (Nginx یا NPM) و صدور گواهی معتبر SSL/TLS (Let's Encrypt).
4. اطمینان از تنظیم `client_max_body_size 15m;` و هدرهای `X-Forwarded-Proto` در کانفیگ پروکسی معکوس.
5. انتقال فایل دیتابیس قبلی `db.sqlite3` و اجرای دستور `docker compose exec web python manage.py migrate_sqlite_to_postgres`.
6. ساخت کاربر ادمین با دستور `docker compose exec -it web python manage.py createsuperuser`.
7. تنظیم وظیفه دوره‌ای (Crontab) برای اجرای خودکار `scripts/backup.sh`.
