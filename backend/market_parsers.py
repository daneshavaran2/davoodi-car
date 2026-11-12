"""Conservative Persian marketplace parsing. Ambiguous prices are not quotes.

This module is deterministic and intentionally avoids hallucinating amounts or
specifications that the seller did not publish.
"""
import re
from datetime import datetime, timezone

DIGITS=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')

def clean(t):
    return re.sub(r'\s+', ' ', str(t or '').translate(DIGITS).replace('ي','ی').replace('ك','ک').replace('‌',' ')).strip().lower()

AMOUNT=re.compile(r'(?<!\d)(\d+(?:\.\d+)?)\s*میلیارد(?:\s*(?:و|،)?\s*(\d+(?:\.\d+)?)\s*میلیون)?(?:\s*(?:تومان|تومن))?|(?<!\d)(\d+(?:\.\d+)?)\s*میلیون(?:\s*(?:تومان|تومن))?|(?<!\d)(\d{7,14})\s*(تومان|تومن|ریال)')
NEGATIVE=re.compile(r'(?:کارمزد|پورسانت|حق\s*الزحمه|پیش\s*پرداخت|بیعانه|ودیعه|اقساط|قسط|ماهانه|هزینه\s*سند|بیمه|مالیات|تخفیف|سود\s*مشارکت|قیمت\s*کارشناسی)')
POSITIVE=re.compile(r'(?:قیمت\s*(?:خودرو|ماشین|فروش|نقدی|قطعی)?|مبلغ\s*فروش|فروش\s*نقدی)')

def parse_price(text):
    """Only return a price if the price context is unambiguous.

    The presence of a separate instalment/fee does not invalidate the car price.
    Never return the 'last number on page' by default.
    """
    t=clean(text).replace(',','').replace('٬','')
    candidates=[]
    for match in AMOUNT.finditer(t):
        a,b,c,d,e=match.groups()
        if a is not None: amount=float(a)*1e9+(float(b or 0)*1e6)
        elif c is not None: amount=float(c)*1e6
        else: amount=float(d)*(0.1 if e=='ریال' else 1)
        val=round(amount)
        if not 50_000_000<=val<=100_000_000_000: continue
        # A label just before the amount is stronger than generic keywords
        # elsewhere in the document. Start at the previous punctuation break.
        prefix=t[max(0,match.start()-90):match.start()]
        clause=re.split(r'[\n؛;،,\.]|\s{2,}',prefix)[-1]
        lastneg=list(NEGATIVE.finditer(clause));lastpos=list(POSITIVE.finditer(clause))
        n=lastneg[-1].start() if lastneg else -1
        p=lastpos[-1].start() if lastpos else -1
        if n>p: continue
        # explicit positive labels are stronger than unlabelled prices
        rank=2 if p>=0 else 1 if not lastneg else 0
        candidates.append((val,rank))
    if not candidates: return None
    chosen=max(rank for _,rank in candidates)
    vals={v for v,r in candidates if r==chosen}
    return next(iter(vals)) if len(vals)==1 else None

WORDS={'صفر':0,'یک':1,'دو':2,'سه':3,'چهار':4,'پنج':5,'شش':6,'هفت':7,'هشت':8,'نه':9,'ده':10,'بیست':20,'سی':30,'چهل':40,'پنجاه':50,'شصت':60,'هفتاد':70,'هشتاد':80,'نود':90,'صد':100,'دویست':200,'سیصد':300}
NUM=r'(?:\d{1,7}|صفر|یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|بیست|سی|چهل|پنجاه|شصت|هفتاد|هشتاد|نود|صد|دویست|سیصد)'

def _count(number):
    if number.isdigit():return int(number)
    return WORDS.get(number)

def parse_mileage(text):
    t=clean(text).replace('٬','').replace(',','')
    # Explicit zero km only if no conflicting positive mileage.
    patterns=[
        rf'\b(?:کارکرد|کار\s*کرده|کیلومتر\s*کارکرد|رفته)\s*[:\-]?\s*({NUM})(?:\s*(هزار|k))?(?:\s*(?:تا|کیلومتر|km))?',
        rf'(?<!\d)({NUM})\s*(هزار|k)?\s*(?:کیلومتر|km|تا\s*کارکرد|تا\s*رفته)',
    ]
    for pat in patterns:
        for m in re.finditer(pat,t):
            num=_count(m.group(1));unit=m.group(2)
            if num is None: continue
            v=num*(1000 if unit else 1)
            # A standalone 4-digit model year must never become mileage.
            if 1350<=v<=1450 or 1950<=v<=2035:
                continue
            if 0<=v<=2_000_000:return v
    if re.search(r'(?<!\w)(?:صفر\s*کیلومتر|کارکرد\s*صفر|بدون\s*کارکرد|خشک\s*کارخانه)(?!\w)',t):return 0
    return None

TRIM_PATTERNS={
    'فیدلیتی': [('پرستیژ',r'پرستیژ|prestige'),('پرایم',r'پرایم|prime'),('الیت',r'الیت|elite')],
    'سانتافه': [('GDI',r'(?<!\w)gdi(?!\w)'),('MPI',r'(?<!\w)mpi(?!\w)'),('۳۳۰۰ سی‌سی',r'3300|۳۳۰۰'),('۲۴۰۰ سی‌سی',r'2400|۲۴۰۰')],
    '۲۰۶': [('تیپ ۲',r'تیپ\s*(?:2|دو)'),('تیپ ۵',r'تیپ\s*(?:5|پنج)'),('تیپ ۶',r'تیپ\s*(?:6|شش)')],
}

def extract_trim(model,text):
    t=clean(text)
    for name,pat in TRIM_PATTERNS.get(str(model or ''),[]):
        if re.search(pat,t,re.I):return name
    return None

def extract_transmission(text):
    t=clean(text)
    if re.search(r'اتومات|automatic|اتومَت',t):return 'اتوماتیک'
    if re.search(r'دنده\s*ای|دنده\s*دستی|manual',t):return 'دستی'
    return None

def extract_condition(text):
    t=clean(text)
    if re.search(r'تعویض\s*اتاق|چپی|شاسی\s*ضربه|تصادفی|آسیب\s*سازه',t):return 'تصادفی / آسیب سازه‌ای'
    if re.search(r'تعویض\s*شده|گلگیر\s*تعویض|درب\s*تعویض',t):return 'تعویض‌شده'
    if re.search(r'رنگ\s*شده|رنگ\s*دار|رنگ\s*خورده|چند\s*لکه\s*رنگ',t) and not re.search(r'بدون\s*رنگ|بی\s*رنگ',t):return 'رنگ‌شده'
    if re.search(r'بی\s*رنگ|بدون\s*رنگ|فابریک\s*بدنه',t):return 'بدون رنگ'
    return None

def is_new_vehicle(text, mileage=None, declared=None):
    if isinstance(mileage,int) and mileage>0: return False
    if declared is False:return False
    if mileage==0:return True
    if declared is True:return True
    return bool(re.search(r'(?<!\w)(?:صفر\s*کیلومتر|کارکرد\s*صفر|بدون\s*کارکرد|خشک\s*کارخانه|آکبند)(?!\w)',clean(text)))

def publication_date(value):
    """Return timezone-aware publication date only; do not confuse crawl time."""
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        seconds=float(value)/1000 if value>1e12 else float(value)
        try: return datetime.fromtimestamp(seconds,timezone.utc).isoformat()
        except (OverflowError,ValueError):return None
    if isinstance(value,str):
        try:
            d=datetime.fromisoformat(value.strip().replace('Z','+00:00'))
            if d.tzinfo:return d.isoformat()
        except ValueError:pass
    return None
