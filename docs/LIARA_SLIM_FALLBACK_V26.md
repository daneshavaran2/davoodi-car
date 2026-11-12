# نسخه آزمایشی Liara — Playwright با Chromium Headless سبک‌تر

## علت ایجاد شاخه

در لاگ Liara مورخ 2026-11-12 آخرین مرحلهٔ قابل مشاهده:
`Step 7/21 : FROM mcr.microsoft.com/playwright/python:v1.57.0-noble`.

**این خط به‌تنهایی خطا نیست**؛ شاید دانلود ایمیج مایکروسافت هنوز ادامه داشته یا به علت محدودیت شبکه/رجیستری متوقف شده باشد. لاگ کامل و نتیجه نهایی در دسترس نبود.

## تفاوت شاخهٔ `liara-slim-playwright`

- از `python:3.12-slim-bookworm` به‌جای `mcr.microsoft.com/playwright/python:v1.57.0-noble` استفاده می‌کند.
- `playwright==1.57.0` را همانند مخزن اصلی نصب می‌کند.
- فقط Chromium headless shell و کتابخانه‌های Debian لازم را به‌وسیلهٔ `python -m playwright install --with-deps --only-shell chromium` دریافت می‌کند.
- مرورگر زیر `/ms-playwright` نصب و برای کاربر غیر root قابل دسترس است.
- مرورگر را هنگام Build با کاربر غیر root و DOM ساختگی باز می‌کند؛ اگر اجرای Chromium ناموفق شود Build با خطای مشخص متوقف می‌شود.
- React و API تغییری نکرده‌اند. مقدار پیش‌فرض `MAX_CONCURRENT_BROWSERS=1` برای کاهش مصرف RAM است.
- **همچنان دانلود Chromium لازم است** و ممکن است CDN مرورگر یا نصب بسته‌های سیستمی در محیط Liara مسدود/کند باشد.

## نحوه آزمایش بدون اختلال در نسخهٔ اصلی

1. در Liara استقرار آزمایشی با شاخهٔ `liara-slim-playwright` و پلتفرم Docker انجام دهید؛ `Dockerfile` در ریشهٔ این شاخه قرار دارد.
2. تنظیمات `ADMIN_PASSWORD`، `SESSION_SECRET` (حداقل ۳۲ نویسه)، `DB_PATH` روی فضای ذخیره‌سازی پایدار و `MARKET_FETCH_MODE=playwright` را تنظیم کنید؛ `MAX_CONCURRENT_BROWSERS=1` برای شروع پیشنهاد می‌شود.
3. خروجی `/api/health` و `/api/readiness`، صفحهٔ React و چند آگهی واقعی را بعد از Deploy بررسی کنید.
4. اگر مرحلهٔ `python -m playwright install` خطا داد، خطای شبکه/دانلود Chromium یا apt را از انتهای لاگ بخوانید؛ آن را به اشتباه به کد استخراج نسبت ندهید.

**وضعیت:** این گزینه فقط در مخزن GitHub تهیه شده و Docker build واقعی و اجرای Liara هنوز تأیید نشده است. تا آزمون کامل، جایگزین سرویس عملیاتی نکنید. از داده‌ها قبل از استقرار پشتیبان بگیرید.

- شاخه: https://github.com/daneshavaran2/davoodi-car/tree/liara-slim-playwright
- Dockerfile جایگزین: https://github.com/daneshavaran2/davoodi-car/blob/liara-slim-playwright/Dockerfile
- مستندات نصب اصلی: https://github.com/daneshavaran2/davoodi-car/blob/main/docs/DOWNLOAD_V26_LIARA_FA.md
