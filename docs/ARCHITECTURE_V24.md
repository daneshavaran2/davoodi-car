# معماری داودی کار نسخه ۲۴

## ترتیب دریافت استعلام

```mermaid
sequenceDiagram
    actor U as کارشناس
    participant F as React
    participant A as FastAPI
    participant J as Job Queue
    participant S as منابع
    participant V as Evidence Engine
    participant DB as SQLite
    U->>F: خودرو، سال، کارکرد، تیپ، بدنه
    F->>A: POST /api/search/jobs
    A->>A: اعتبارسنجی فیلدهای ضروری + نشست + نرخ
    alt اطلاعات کافی نیست
      A-->>F: 422 + سؤال تکمیلی
      F-->>U: نمایش همان سؤال
    else معتبر است
      A->>DB: ذخیره کار با وضعیت queued
      A-->>F: 202 + job_id
      A->>J: اجرای job در همین process
      J->>S: درخواست مستقل هر دامنه
      S-->>J: آگهی/قیمت مرجع/خطا
      J->>V: استخراج تاریخ، قیمت، تطابق، حذف تکراری
      V-->>J: شواهد معتبر + نیازمند بررسی
      J->>DB: ثبت نتیجه و وضعیت
      loop هر یک ثانیه
        F->>A: GET /api/search/jobs/{id}
        A-->>F: پیشرفت واقعی منابع
      end
      A-->>F: نتیجه یا خطا
      F-->>U: خلاصه قیمت و لینک شواهد
    end
```

## مسیر تصمیم‌گیری درباره قیمت

```mermaid
flowchart TD
 A[صفحه/آگهی بازیابی شده] --> B{نوع صفحه آگهی یا مرجع است؟}
 B -->|خیر| X[حذف: مقاله / خبر / راهنما]
 B -->|بله| C{قیمت کامل و غیرمبهم دارد؟}
 C -->|خیر| R[نیازمند بررسی / بدون قیمت]
 C -->|بله| D{سال، مدل، تیپ و بدنه تایید شده؟}
 D -->|خیر| R
 D -->|بله| E{تاریخ انتشار واقعی معتبر و جدید؟}
 E -->|خیر| R
 E -->|بله| F[حذف تکراری و پرت]
 F --> G{حداقل ۳ شاهد، ۲ آگهی، ۲ دامنه؟}
 G -->|خیر| L[شواهد محدود؛ بدون میانگین بازار]
 G -->|بله| P[محاسبه میانه، دامنه و قیمت پیشنهادی]
```

## ساختار سرویس‌ها

- `main.py`: API، login/logout، token revocation، cache، domain scheduling، jobs/history.
- `market_parsers.py`: parsing صرفاً قاعده‌محور و محافظه‌کارانه؛ fail closed on ambiguous price.
- `market_intelligence.py`: مشخصات و اصالت شواهد، freshness، de-dup، quality score، statistics.
- `connectors/`: فقط داده عمومی، timeout، و تلاش برای metadata در JSON-LD.
- `vehicle_nlp.py`: alias + user confirmation؛ AI/LLM قیمت تولید نمی‌کند.
- `frontend/`: ورود، فرم، ابهام‌زدایی، پیشرفت واقعی، خلاصه قیمت و نمودار.

## محدودیت در چند replica

SQLite برای یک instance مناسب است. ThreadPoolExecutor «صف پایدار توزیع‌شده» نیست؛ اگر Liara instance را restart کند task در حال اجرا از دست می‌رود و خواندن کار باید timeout شود. برای مقیاس‌پذیری، Redis + RQ/Celery + Postgres و idempotency لازم است.
