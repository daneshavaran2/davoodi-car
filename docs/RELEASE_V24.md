# Davoodi Car v24 — Release Candidate QA

تاریخ: ۱۲ نوامبر ۲۰۲۶

## اصلاحات و شواهد آزمون

| حوزه | اصلاح | آزمون |
|---|---|---|
| قیمت | جدا کردن کارمزد/اقساط/ودیعه از قیمت خودرو؛ امتناع در ابهام | test_price_ignores_commission, test_price_rejects_financing_only, test_ambiguous_two_prices_abstain |
| کارکرد | تشخیص «کارکرد ۵۰ هزار» مستقل از سال ۱۴۰۳ | test_mileage_year_not_borrowed |
| تیپ | جلوگیری از ترکیب پرایم و پرستیژ؛ سؤال تکمیلی در حالت نامعلوم | test_variant_conflict, test_unknown_variant_rejected_when_specific |
| صفر و کارکرده | «تحویل فوری» دلیل صفر بودن نیست | test_delivery_now_is_not_new, test_no_unknown_zero_evidence |
| بدنه/رنگ | رد آگهی‌های مغایر با وضعیت بدنه و رنگ معلوم | test_body_damage_mismatch, test_body_dent_is_not_clean, test_color_mismatch_rejects_when_known |
| امنیت ورود | محدودیت پنج ورود ناموفق در ۱۵ دقیقه بر مبنای IP، توقف ۵ دقیقه | test_throttle_failed_login |
| اتصال منابع | استخراج JSON-LD در آگهی‌های عمومی، بررسی دامنه معتبر | test_jsonld_offer_and_actual_posting_date, test_bama_link_host_not_substring |
| هم‌زمانی | سه جست‌وجوی هم‌زمان در هر پردازش، عدم صف جهانی یک‌تایی | test_three_parallel_requests_do_not_global_queue |
| پیشرفت | endpoint محافظت‌شده که مرحله واقعی جست‌وجو را گزارش می‌کند | test_progress_endpoint_records_actual_stage, test_progress_requires_auth |
| کش | سقف سن پاسخ ذخیره‌شده در fallback اضطراری | بررسی کد، آزمون بیشتر پس از استقرار توصیه می‌شود |

**تست‌های اجراشده در محیط توسعه:** ۱۱ تست v22، ۲۱ تست v23، ۱۹ تست v24، تست‌های یکپارچگی v21 و ۱۱ بررسی React/voice fallback با Node. همه در داده‌های ساختگی آفلاین موفق شدند. compileall بک‌اند و transpile نحوی JSX نیز بدون خطا بودند.

## محدودیت‌های حیاتی پیش از انتشار عمومی

- `npm install --offline` با خطای ENOTCACHED و `npm install` با EAI_AGAIN متوقف شد؛ build Vite در محیط فعلی قابل تأیید نبود.
- Docker CLI موجود نبود؛ build Docker محلی تأیید نشد.
- API واقعی AvalAI با کلید معتبر و سایت‌های بازار ایران تست زنده نشده‌اند.
- رفتار روی Chrome/Edge/Safari موبایل، میکروفن واقعی و کیفیت رابط بصری باید به‌صورت عملی تست شود.
- Rate limit و job progress در حافظه همان process است؛ اگر Liara چند replica داشته باشد، برای رفتار سازگار از Redis/DB مرکزی استفاده کنید.
- قفل سه جست‌وجوی هم‌زمان بر اساس هر process است، نه کل خوشه.
- رابط فقط فیدلیتی با تیپ دقیق را قیمت‌گذاری می‌کند؛ اگر تیپ نامعلوم باشد، خطای راهنمای ۴۲۲ نمایش داده می‌شود.
- کانکتورهای سایت‌های ثالث ممکن است از نظر دسترسی، پایداری یا ساختار داده محدود باشند. هیچ قیمت روز واقعی در این گزارش ادعا نشده است.

## پذیرش نهایی Liara

۱. CI سبز: همه تست‌های Python و React build و Docker build.
۲. API سلامت `/api/health` نسخه `24.0.0-quality-security` و `/api/readiness` وضعیت DB را نشان دهد.
۳. سناریوهای منفی: نام مدل مبهم، تیپ مجهول، اقساط، 429، منبع خارج دامنه، کش منقضی.
۴. ۱۵ آگهی واقعی از حداقل ۳ منبع و چند مدل ایرانی، چینی و وارداتی را دستی با لینک واقعی تطبیق دهید.
۵. کنترل دستی قیمت/کارکرد/سال/بدنه/تیپ در آگهی و گزارش: هر اختلاف بحرانی باید رفع شود.
۶. مرورگر موبایل، صفحه‌کلید فارسی، میکروفن و accessibility را روی دستگاه واقعی بررسی کنید.
۷. در محیط production از secret قوی، TLS، فضای دائمی DB و پشتیبان‌گیری استفاده کنید.
۸. نسخه بعد از قبولی آزمون‌ها به‌عنوان نسخه پایدار منتشر شود؛ تا آن زمان v24 نامزد انتشار است.
