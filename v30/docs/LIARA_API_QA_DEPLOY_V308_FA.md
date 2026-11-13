# استقرار هماهنگ Web و Worker نسخه ۳۰.۸ داودی‌کار با API لیارا

**نکته:** کد و گردش‌کار GitHub آماده‌اند؛ تا تأیید موفق GitHub Actions، انتشار واقعی لیارا و دریافت آگهی معتبر، وضعیت «منتشرشده و عملیاتی» اعلام نمی‌شود.

## دو برنامه مستقل در Liara
۱. `davoodicar` — React و API FastAPI؛ جست‌وجوی کاربر فقط از PostgreSQL. باید در `https://davoodicar.liara.run/api/v1/health` نسخه `30.8.0` و `database=ok` نمایش داده شود.

۲. `davoodicar-worker` — Playwright + خزش، اعتبارسنجی و محاسبه بازه. باید در `https://davoodicar-worker.liara.run/api/live` نسخه `30.8.0` و `database_bootstrapped=true` نمایش داده شود.

**ترتیب اجباری:** ابتدا Web تا migration 005 روی PostgreSQL اعمال و سلامت دیتابیس تأیید شود، سپس Worker. استقرار Worker قبل از migration جدید ممکن است باعث خطای `column ... does not exist` شود.

## اجرای GitHub Actions
از `Settings → Secrets and variables → Actions`، متغیر محرمانه `LIARA_API_TOKEN` را تعریف کنید. در صورت نیاز `LIARA_TEAM_ID` را نیز اضافه کنید. توکن را در چت یا فایل مخزن قرار ندهید.

گردش‌کار `.github/workflows/deploy-liara-worker.yml` ابتدا تست‌های آفلاین، ساخت آرشیو بدون رمز و Docker هر دو نقش را انجام می‌دهد. **اگر هرکدام شکست بخورد، استقرار شروع نمی‌شود.** سپس طبق API رسمی:
- ZIP وب به `POST /v2/projects/davoodicar/sources` و `POST /v2/projects/davoodicar/releases`
- بررسی سلامت نسخه ۳۰.۸ وب
- ZIP Worker به `POST /v2/projects/davoodicar-worker/sources` و `POST /v2/projects/davoodicar-worker/releases`
- بررسی سلامت نسخه ۳۰.۸ Worker

در درخواست Release، `envs` عمداً ارسال نمی‌شود تا تنظیمات محرمانه `DATABASE_URL` و سایر envهای فعلی جایگزین نشوند.

مستندات رسمی: https://github.com/liara-cloud/openapi

## آزمون بدون توکن و بدون درخواست شبکه
```bash
python v30/scripts/deploy_liara_api.py --role web --dry-run
python v30/scripts/deploy_liara_api.py --role worker --dry-run
```

بعد از استقرار، فقط **باما** را فعال کنید و تاریخچه `public_crawl_history`، تعداد `cards_seen`، `evidence_rejected`، `detail_conflicts` و `accepted_listings` را بررسی کنید. نمونه‌های واقعی قیمت باید با صفحه آگهی مطابقت داده شوند.

## محدودیت‌های آزمون
نسخه ۳۰.۴ وب قبلاً با ۵۸ تست آفلاین گذشت؛ ۸ آزمون جداگانه کیفیت با محیط محلی هم موفق شدند، اما **این نتیجه آزمون یکپارچهٔ آخرین نسخه ۳۰.۸ نیست**. GitHub Actions تاکنون ناموفق گزارش شده و دریافت لاگ بعضی jobها با `BlobNotFound` مواجه شده است. تا رفع CI و آزمون پذیرش زنده، قیمت‌های واقعی و سرعت کمتر از ۳ ثانیه تأیید نشده‌اند.
