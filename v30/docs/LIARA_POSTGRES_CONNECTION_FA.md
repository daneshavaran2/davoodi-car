# اتصال PostgreSQL نسخه ۳۰.۱ داودی‌کار به Liara

**وضعیت:** کد و دستور بررسی اتصال آماده است. ایجاد دیتابیس/انتشار روی حساب Liara و موفقیت اتصال زنده از این گفتگو تأیید نشده است. توکن ورود Liara معادل آدرس یا رمز دیتابیس نیست.

## ۱. دیتابیس در Liara
1. در پنل Liara بخش Databases یک PostgreSQL خصوصی در شبکه برنامه ایجاد یا دیتابیس موجود را انتخاب کنید.
2. اطلاعات **Private Host، Port، Database، Username، Password** را از پنل بگیرید؛ اطلاعات محرمانه را در GitHub یا چت ثبت نکنید.
3. روی برنامه آزمایشی Docker و Worker جداگانه، متغیر `DATABASE_URL` را با **یک مقدار مشترک** تنظیم کنید؛ آدرس `postgres` از Docker Compose روی Liara معتبر نیست.

نمونه قالب تنظیمات (نمونه، نه رمز واقعی):

```env
DATABASE_URL=postgresql://DB_USER:URL_ENCODED_PASSWORD@LIARA_PRIVATE_DB_HOST:DB_PORT/DB_NAME
ADMIN_TOKEN=CHOOSE_A_NEW_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
SERVICE_ROLE=web
DB_WAIT_ATTEMPTS=12
DB_WAIT_INTERVAL=3
```

برای برنامه Worker، `SERVICE_ROLE=worker` و `SCHEDULER_TZ=Asia/Tehran` تعریف کنید. اگر گذرواژه شامل `@`، `:`، `/`، `#` یا `%` است، آن را در URL با percent encoding درج کنید؛ در صورت الزام SSL از `?sslmode=require` مطابق مشخصات ارائه‌شده استفاده کنید.

## ۲. انتشار و آزمون
1. ابتدا از برنامه و دیتابیس فعلی پشتیبان بگیرید و نسخه ۳۰.۱ را روی سرویس Docker **آزمایشی** منتشر کنید. ریشه Build همان پوشه `v30` دارای `Dockerfile` است.
2. دستور Start را روی پیش‌فرض Dockerfile یعنی `python -m scripts.liara_entrypoint` بگذارید. Frontend باید در مرحله Build ساخته شود.
3. برنامه Web با `SERVICE_ROLE=web` فوراً پورت HTTP را باز می‌کند و bootstrap دیتابیس جداگانه تلاش می‌شود. در Logs به دنبال `WEB_LISTEN` و بعد `DB_BOOTSTRAP_OK` باشید.
4. در Shell کانتینر وب دستور زیر را اجرا کنید:

```bash
python -m scripts.check_liara_db
# بعد از تأیید اینکه به دیتابیس مختص داودی‌کار وصل هستید:
python -m scripts.setup_liara_postgres --apply
# بررسی فقط‌خواندنی بعد از اجرای migration و import:
python -m scripts.setup_liara_postgres
```

تست باید پس از اتصال واقعی، `PostgreSQL connection established` و `vehicle_models table exists; rows: 660` را چاپ کند؛ رمز و URL محرمانه چاپ نمی‌شود.

5. مسیرهای زیر را روی دامنه **آزمایشی** بررسی کنید:

```bash
curl -i https://YOUR_TEST_APP.liara.run/api/live
curl -i https://YOUR_TEST_APP.liara.run/api/v1/health
```

`/api/live` سلامت اجرای HTTP را گزارش می‌کند، اما به معنی سالم بودن PostgreSQL نیست. `/api/v1/health` تنها پس از آماده بودن PostgreSQL و کاتالوگ ۶۶۰ مدلی باید `200` و `database: ok` برگرداند. اگر `503` با `DATABASE_URL_MISSING`، `DATABASE_UNAVAILABLE`، `SCHEMA_NOT_READY` یا `CATALOG_NOT_READY` برگشت، خطا را از اتصال و migration پیگیری کنید.

6. Worker مستقل را با همان دیتابیس در سرویس جداگانه راه‌اندازی کنید. در نبود DB، Worker عمداً شروع به جمع‌آوری نمی‌کند.
7. تا قبل از آزمایش یک یا چند منبع مجاز، قیمت زنده و تکمیل داده‌های بازار را تأیید نکنید؛ شش کانکتور به‌صورت پیش‌فرض غیرفعال‌اند.

## ۳. عیب‌یابی
| علامت | اقدام |
|---|---|
| `DATABASE_URL_MISSING` | تعریف متغیر در Environment هر دو سرویس |
| خطای DNS | بررسی Private Host و شبکه Liara |
| خطای رمز | تأیید کاربر/رمز، percent encoding |
| Connection refused | وضعیت DB و پورت و Host خصوصی |
| SSL required | تنظیم SSL مطابق نیاز سرویس |
| Catalog count != 660 | بررسی اجرای `scripts.bootstrap`، migration و importer |
| `/api/live` هم 502 | بررسی Start Command، پورت، حافظه، Container Logs و نسخه مستقر |
| صفحه قدیمی ورود دستی/صدا | React یا سرویس قدیمی هنوز منتشر است؛ کش و image مستقر را بررسی کنید |

**امنیت:** توکن Liara که در گفتگو ارسال شده باید لغو و جایگزین شود. هیچ توکن یا رمز واقعی در مخزن ثبت نشود. این مستند راهنمای عملیاتی است، نه ادعای انجام اتصال.


## ۴. وضعیت اجرا و نکات امنیتی
- ساخت Instance جدید PostgreSQL در Liara ممکن است هزینه ایجاد کند؛ این مرحله بدون انتخاب پلن/شبکه در پنل انجام نشود.
- اسکریپت `setup_liara_postgres --apply` **فقط داخل PostgreSQL موجود** جداول داودی‌کار را به‌صورت idempotent ایجاد/تکمیل کرده و کاتالوگ را upsert می‌کند؛ Instance جدید Liara ایجاد نمی‌کند.
- اجرای دستور تنها وقتی درست است که متغیر `DATABASE_URL` به دیتابیس مخصوص برنامه داودی‌کار اشاره کند؛ روی دیتابیس برنامه‌های دیگر اجرا نکنید.
- `source`ها بعد از migration به‌صورت پیش‌فرض **غیرفعال** می‌مانند و هیچ قیمت مصنوعی وارد نمی‌شود.
- توکن مدیریتی یا `DATABASE_URL` را در GitHub Actions، issue، لاگ و پاسخ پشتیبانی کپی نکنید؛ فقط در Secrets/Environment بگذارید.
