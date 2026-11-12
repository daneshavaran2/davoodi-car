# API و راهنمای استقرار Liara

## API
- `GET /api/health` — سلامت و نسخه
- `POST /api/login` — ورود
- `POST /api/parse-voice` — استخراج مشخصات از متن گفتار
- `POST /api/search` — استعلام قیمت
- `GET /api/history` و `GET /api/history/{item_id}` — تاریخچه
- `POST /api/compare` — مقایسه
- `GET /api/catalog` و `GET /api/catalog/suggest` — کاتالوگ
- `POST /api/catalog/discover` — کشف مدل
- `GET /api/car-image` و `GET /api/brand-logo` — تصویر و لوگو

## استقرار
1. محتوای ZIP را استخراج کنید.
2. `Dockerfile` در ریشه پروژه است؛ استقرار را از نوع Docker تنظیم کنید.
3. `ADMIN_PASSWORD` و `SESSION_SECRET` (حداقل ۳۲ نویسه) را در Environment Variables لیارا قرار دهید.
4. کلیدهای API فقط در محیط امن باشند؛ فایل `.env` را در GitHub نگذارید.
5. برای SQLite از فضای ذخیره‌سازی پایدار استفاده کنید؛ `DB_PATH` را متناسب تنظیم کنید.
6. پس از انتشار `GET /api/health` را بررسی کنید؛ نسخه مورد انتظار `20.0.0-fidelity-year-fix` است.
7. گفتار «خودرو فیتیلی 2025» و «فیدلیتی مدل ۲۰۲۵ کارکرد ۵۰ هزار کیلومتر» را آزمایش کنید.

**وضعیت:** تست تابع پردازش گفتار انجام شده؛ build Docker و استقرار زنده تأیید نشده‌اند.
