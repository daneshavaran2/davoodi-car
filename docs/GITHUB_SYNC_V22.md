# همگام‌سازی سورس نسخه ۲۲ در GitHub

تاریخ: ۱۲ نوامبر ۲۰۲۶.

نسخه ۲۲ به طور مستقیم از پوشه پروژه مورد استفاده برای فایل ZIP انتشار Liara به این مخزن انتقال داده شد.

## فایل‌های کلیدی
- `backend/main.py` — API و موتور اصلی
- `backend/market_intelligence.py` — امتیازدهی، فیلتر و تحلیل شواهد
- `backend/vehicle_nlp.py` — تشخیص مدل خودرو از گفتار
- `backend/connectors/` — کانکتورهای بازار
- `frontend/src/main.jsx` و `frontend/src/style.css` — رابط مدیریتی React
- `backend/test_v21_market_fix.py` و `backend/test_v22_intelligence.py` — تست‌های آفلاین
- `Dockerfile`، `.env.example`، تصاویر و مستندات

## وضعیت آزمایش
تست‌های آفلاین backend نسخه‌های ۲۱ و ۲۲ در محیط ساخت موفق بوده‌اند. build فرانت‌اند در محیط ساخت به دلیل نبود وابستگی‌های npm در کش محلی تأیید نشد. اجرای واقعی لیارا، تماس با منابع بازار و CI هنوز نیازمند تأیید بعد از Push است.

## CI
`.github/workflows/ci.yml` پس از Push، تست Python و build فرانت‌اند و Docker را اجرا می‌کند. هیچ رمز واقعی یا API key در مخزن قرار ندهید.
