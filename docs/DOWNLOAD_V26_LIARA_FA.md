# دریافت نسخه v26 داودی‌کار برای Liara

**دانلود مستقیم کد کامل (ZIP از شاخه main):**
https://github.com/daneshavaran2/davoodi-car/archive/refs/heads/main.zip

این آدرس، آرشیو رسمی کد مخزن GitHub است، نه یک فایل Release مستقل؛ داخل آن Dockerfile، backend، frontend و تست‌ها قرار دارند. فایل ZIP یک تصویر Docker ازپیش‌ساخته‌شده نیست.

اگر لینک در مرورگر باز نشد:
1. به https://github.com/daneshavaran2/davoodi-car بروید و از `Code → Download ZIP` استفاده کنید.
2. یا روی رایانه‌ای که Git نصب دارد:
   ```powershell
   git clone --depth 1 https://github.com/daneshavaran2/davoodi-car.git
   cd davoodi-car
   ```
3. برای ساخت ZIP محلی در PowerShell (خارج از پوشه پروژه):
   ```powershell
   Compress-Archive -Path .\davoodi-car\* -DestinationPath .\DavoodiCar_v26_Liara.zip -Force
   ```

## استقرار آزمایشی روی Liara
- کد را با پلتفرم Docker و فایل `Dockerfile` ریشه پروژه Build کنید؛ از روش اجرای مستقیم Python (بدون Docker) برای Playwright استفاده نکنید.
- `ADMIN_PASSWORD`، `SESSION_SECRET` (حداقل ۳۲ حرف)، `DB_PATH` روی مسیر ذخیره‌سازی پایدار، `MARKET_FETCH_MODE=playwright` و `MAX_CONCURRENT_BROWSERS=1` برای منابع کم‌حافظه تنظیم کنید. در صورت امکان Chromium را با ظرفیت کافی و سپس مقدار ۲ آزمایش کنید.
- کلیدهای محرمانه را فقط در تنظیمات Environment/Secrets خود Liara نگهداری کنید؛ در GitHub قرار ندهید.
- پیش از جایگزینی سرویس اصلی، از داده‌ها نسخه پشتیبان بگیرید و تست را روی محیط مجزا انجام دهید.
- پس از استقرار `https://davoodicar.liara.run/api/health` و `/api/readiness`، صفحه React و چند آگهی عمومی واقعی را بررسی کنید. Readiness به‌تنهایی صحت استخراج قیمت را ثابت نمی‌کند.

## وضعیت واقعی CI (۱۲ نوامبر ۲۰۲۶)
اجرای GitHub Actions به شماره `43284108782` ناموفق بود؛ Jobهای backend، frontend و playwright-browser بدون اختصاص Runner و بدون اجرای Step متوقف شده‌اند. بنابراین **از این نتیجه نمی‌شود به وجود خطا در تست‌ها پی برد**. ابتدا وضعیت اجرای GitHub Actions، محدودیت‌های حساب و سهمیه/صورتحساب GitHub را در تنظیمات حساب/مخزن بررسی کنید. پس از آن اجرای موفق CI و ساخت Docker برای انتشار الزامی است.

**محدودیت:** استخراج زنده از دیوار، باما و سایر منابع تأیید نشده؛ Playwright دسترسی به همه سایت‌ها یا دورزدن کپچا/۴۰۳/۴۲۹ را تضمین نمی‌کند.
