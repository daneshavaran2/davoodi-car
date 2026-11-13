# آزمون و استقرار Worker داودی‌کار ۳۰.۷ با API رسمی Liara

**وضعیت:** GitHub Action برای اجرای تست‌های آفلاین، ساخت Docker، ایجاد آرشیو، آپلود ZIP به API لیارا و ایجاد Release تنظیم شده است. این فایل به معنی اجرای موفق استقرار نیست. نتیجهٔ واقعی را باید در GitHub Actions و در Liara مشاهده کرد.

## پیش‌نیاز بدون افشای رمز
در GitHub مخزن `daneshavaran2/davoodi-car`، قسمت:
`Settings → Secrets and variables → Actions → New repository secret`
این متغیر را به‌شکل Secret تعریف کنید:
`LIARA_API_TOKEN`
اگر برنامه متعلق به Team است، `LIARA_TEAM_ID` را نیز تنظیم کنید.
**توکن را در README، کد، Issues یا چت وارد نکنید.** توکن‌هایی را که قبلاً افشا شده‌اند تعویض کنید.

## اجرای خودکار یا دستی
Workflow `DavoodiCar v30.7 Worker QA + Liara API` هنگام تغییر مسیرهای Worker روی شاخه اصلی اجرا می‌شود؛ یا در Actions می‌توان `Run workflow` زد. تا زمانی که آزمون‌ها موفق نشوند، استقرار انجام نمی‌شود. وقتی Secret وجود داشته باشد، workflow از Liara REST API استفاده می‌کند:

۱. `POST /v2/projects/davoodicar-worker/sources` همراه ZIP Worker و Authorization Bearer.

۲. `POST /v2/projects/davoodicar-worker/releases` با `type=docker`، `port=8000`، و `sourceID` مرحله قبل.

در هیچ مرحله `envs` به API ارسال نمی‌شود تا DATABASE_URL، ADMIN_TOKEN و سایر متغیرهای محیطی موجود در Liara جایگزین نشوند.

۳. بررسی `https://davoodicar-worker.liara.run/api/live` برای نسخه `30.7.0` و `database_bootstrapped=true`.

## تست محلی بدون API
```bash
cd v30
python -m pip install -r requirements.worker.txt pytest httpx
python -m pytest -q
python scripts/deploy_liara_api.py --dry-run
```

آزمایش dry-run هیچ درخواست اینترنتی ارسال نمی‌کند و نسخه Worker را در ZIP کنترل می‌کند.

## بعد از انتشار
برای شروع از یک منبع (باما) و دریافت داده واقعی استفاده کنید. در قسمت مدیریت منابع فقط باما روشن باشد. سپس بازدید صفحات و مدل‌ها را بررسی کنید:
`https://davoodicar-worker.liara.run/api/worker/health`

در صورت مشاهده `HTTP_403`، `HTTP_429`، `CAPTCHA_OR_CHALLENGE`، `CATEGORY_NOT_FOUND` یا `NO_VERIFIED_LISTINGS` باید برای همان منبع علت عملی را در لاگ بررسی کرد، نه اینکه از روی سالم بودن PostgreSQL نتیجه گرفت استخراج موفق بوده است.

**محدودیت فعلی ابزار گفتگو:** دسترسی احراز هویت‌شده به Liara API در این گفتگو موجود نیست؛ این workflow راه امن استقرار با Secret اختصاصی خودتان است. نتیجه GitHub Actions و لاگ Liara ملاک تأیید نهایی است.
