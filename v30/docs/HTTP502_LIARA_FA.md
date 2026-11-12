# اصلاح HTTP 502 در Liara — داودی‌کار نسخه 30.1

**علت قطعی خطای موجود باید از لاگ خود Liara تأیید شود.** در نسخه قبلی، شروع وب پس از اجرای Bootstrap دیتابیس بود؛ اگر PostgreSQL در دسترس نبود، Uvicorn اصلاً شروع نمی‌شد و Reverse Proxy ممکن بود 502 بدهد.

## تغییرات
- هنگام اجرای `SERVICE_ROLE=web` وب‌سرور فوراً روی `0.0.0.0:$PORT` شروع می‌شود؛ راه‌اندازی دیتابیس با تلاش مجدد در پس‌زمینه انجام می‌شود.
- `GET /api/live`: سلامت پردازش HTTP (200، حتی اگر DB قطع باشد).
- `GET /api/v1/health` یا `/api/health`: وضعیت واقعی دیتابیس و کاتالوگ؛ در خطا JSON با HTTP 503 و کد `DATABASE_URL_MISSING`، `DATABASE_UNAVAILABLE`، `SCHEMA_NOT_READY` یا `CATALOG_NOT_READY`.
- خطاهای API به فرانت کاربرپسند تبدیل می‌شوند؛ نه پیام مبهم «API پاسخ JSON نداد».
- `SERVICE_ROLE=worker` فقط در صورت موفقیت Bootstrap فعال می‌شود.

## عملیات موردنیاز در Liara
1. از برنامه و PostgreSQL نسخه پشتیبان تهیه کنید.
2. Docker Build نسخه 30.1 را روی **برنامه آزمایشی** منتشر کنید؛ Dockerfile، React را می‌سازد.
3. از تنظیمات Environment مقدارهای `SERVICE_ROLE=web`، `DATABASE_URL` (نشانی خصوصی واقعی PostgreSQL در Liara)، `ADMIN_TOKEN` و `PORT` را بررسی کنید. آدرس `postgres` در Docker Compose **در شبکه Liara معتبر نیست**.
4. Start Command را سفارشی نکنید؛ دستور Dockerfile یعنی `python -m scripts.liara_entrypoint` را نگه دارید.
5. در Shell/Logs دنبال `WEB_LISTEN` و `DB_BOOTSTRAP_OK` بگردید. اگر `DB_BOOTSTRAP_RETRY` وجود دارد، خطای PostgreSQL را از تنظیمات Liara رفع کنید.
6. Liveness را در صورت نیاز `/api/live` و Readiness را `/api/v1/health` قرار دهید.
7. Worker مستقل را با همان `DATABASE_URL` و `SERVICE_ROLE=worker` اجرا کنید.

## تست‌های فوری
```bash
curl -i https://davoodicar.liara.run/api/live
curl -i https://davoodicar.liara.run/api/v1/health
curl -i https://davoodicar.liara.run/api/v1/vehicles/search?q=fidelity
```
اگر `/api/live` هم 502 شد، مشکل از اجرای/پورت/حافظه کانتینر یا routing است؛ لازم است **لاگ واقعی Liara** بررسی شود. اگر `/api/live` برابر 200 و `/api/v1/health` برابر 503 بود، سرور اجراست اما دیتابیس/کاتالوگ آماده نیست. **404 در مسیرهای v1** نشان می‌دهد نسخه 30.1 احتمالاً منتشر نشده است.

**نکته:** نمای قدیمی «ورود دستی / ورود با صدا» متعلق به فرانت قدیمی است؛ برای کار با API نسخه 30.1 باید Frontend و Backend همان Image ساخته شوند. اتصال زنده منابع خودرو در این مرحله تضمین نشده است.

**امنیت:** توکن قبلاً ارسال‌شده در چت را در Liara باطل و جایگزین کنید. مقادیر محرمانه را در GitHub ثبت نکنید.
