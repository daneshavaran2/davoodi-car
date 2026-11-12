"""Conservative parsing and evidence checks for Iranian car listings.

These functions reject ambiguity instead of inventing prices, years, or body state.
"""
import re
from urllib.parse import urlsplit
from datetime import datetime, timezone

DIGITS=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')

def normalize(s):
    return re.sub(r'\s+',' ',str(s or '').translate(DIGITS).replace('ي','ی').replace('ك','ک').replace('٬','').replace(',','').replace('‌',' ')).strip().lower()

FEE=r'کارمزد|حق\s*الزحمه|هزینه\s*(?:انتقال|سند|خدمات)|بیمه|مالیات|قسط|اقساط|پیش\s*پرداخت|ودیعه|بیعانه|تخفیف'
ASK=r'قیمت\s*(?:فروش|خودرو|ماشین|نهایی|نقدی|آگهی)?|بهای\s*(?:فروش|خودرو)|مبلغ\s*فروش|فروش\s*نقدی'

def explicit_vehicle_price(text):
    """Require a price-bearing phrase, reject fee/financing amounts.

    If multiple distinct unlabelled car-price candidates are present, abstain.
    """
    t=normalize(text)
    candidates=[]; occupied=[]
    patterns=[
      (r'(?<!\d)(\d+(?:\.\d+)?)\s*میلیارد(?:\s*(?:و|،)?\s*(\d+(?:\.\d+)?)\s*میلیون)?\s*(?:تومان)?',1_000_000_000),
      (r'(?<!\d)(\d+(?:\.\d+)?)\s*میلیون\s*(?:تومان)?',1_000_000),
      (r'(?<!\d)(\d{7,13})\s*تومان',1),
      (r'(?<!\d)(\d{8,14})\s*ریال',.1),
    ]
    for pattern,factor in patterns:
      for match in re.finditer(pattern,t):
        if any(match.start()<end and match.end()>start for start,end in occupied):continue
        occupied.append(match.span())
        amount=int(float(match.group(1))*factor)
        if factor==1_000_000_000 and match.lastindex and match.lastindex>=2 and match.group(2):
            amount+=int(float(match.group(2))*1_000_000)
        if not 50_000_000<=amount<=100_000_000_000:continue
        context=t[max(0,match.start()-48):match.start()]
        # The nearest clause matters: a price in a different clause is not a fee.
        context=re.split(r'[،؛؛\n.]|\s+(?:ولی|اما|درحالی\s*که)\s+',context)[-1]
        context=context[-36:]
        fee=bool(re.search(FEE,context))
        asking=bool(re.search(ASK,context))
        candidates.append((amount,asking,fee))
    viable=[(a,explicit) for a,explicit,fee in candidates if not fee]
    if not viable:return None
    priority={a for a,explicit in viable if explicit}
    if len(priority)==1:return priority.pop()
    if len(priority)>1:return None
    values={a for a,_ in viable}
    return next(iter(values)) if len(values)==1 else None

def mileage_from_description(text):
    t=normalize(text)
    if re.search(r'(?<!\w)(?:صفر\s*کیلومتر|بدون\s*کارکرد)(?!\w)',t):return 0
    pats=[
      (r'(?:کارکرد|کار\s*کرد|کیلومتر\s*کارکرد)\s*[:：-]?\s*(\d{1,7})\s*هزار(?:\s*(?:کیلومتر|km))?',1000),
      (r'(?:کارکرد|کار\s*کرد|کیلومتر\s*کارکرد)\s*[:：-]?\s*(\d{1,7})\s*(?:کیلومتر|km)?',1),
      (r'(?<!\d)(\d{1,7})\s*هزار\s*(?:تا\s*)?(?:کارکرد|کیلومتر|km)',1000),
      (r'(?<!\d)(\d{1,7})\s*(?:کیلومتر|km)(?:\s*کارکرد)?',1),
      (r'(?<!\d)(\d{1,7})\s*تا\s*(?:کارکرد|کار\s*کرده)',1),
    ]
    for pat,mul in pats:
      for m in re.finditer(pat,t):
        n=int(m.group(1))*mul
        if 0<=n<=2_000_000:
          if 1350<=n<=2100 and mul==1 and 'مدل' in t[max(0,m.start()-10):m.start()]:continue
          return n
    return None

def new_status(text, structured_mileage=None, explicit_new=None):
    if structured_mileage is not None:
      if structured_mileage>0:return False
      if structured_mileage==0:return True
    t=normalize(text)
    if re.search(r'(?:کارکرده|دست\s*دوم|دست\s*دو|بدون\s*رنگ\s*با\s*کارکرد)',t):return False
    if re.search(r'(?<!\w)(?:صفر\s*کیلومتر|بدون\s*کارکرد|آکبند|اکبند)(?!\w)',t):return True
    if explicit_new is True:return True
    return None  # «تحویل فوری» is NOT evidence of 0 km.

def body_group(text):
    t=normalize(text)
    if re.search(r'تصادف|شاسی|ستون\s*آسیب|دو\s*تکه',t):return 'structural'
    if re.search(r'تعویض|عوض\s*شده',t):return 'replaced'
    if re.search(r'ضربه|تو\s*رفتگی|فرورفتگی',t):return 'damaged'
    if re.search(r'رنگ\s*شد|رنگ\s*خور|چند\s*لکه|لکه\s*رنگ',t):return 'painted'
    if re.search(r'بدون\s*رنگ|بی\s*رنگ|بیرنگ|فابریک|بی\s*خط\s*و\s*خش',t):return 'clean'
    return None

def trim_status(expected, observed, text):
    """Known variant families must not silently contaminate base-model quotes."""
    req=normalize(expected).strip()
    hay=normalize((observed or '')+' '+(text or ''))
    variants=('پرایم','پرستیژ','الیت')
    seen=[v for v in variants if re.search(r'(?<!\w)'+v+r'(?!\w)',hay)]
    if req:
      if req in variants:
        return (req in seen) if seen else None
      if seen and req not in seen:return False
      if normalize(observed) and req!=normalize(observed):return False
      return True if req in hay else None
    return None if seen else True


def exterior_color(text):
    t=normalize(text)
    aliases={'سفید':('سفید',),'مشکی':('مشکی','سیاه'),'نقره‌ای':('نقره ای','نقره‌ای'),
        'خاکستری':('خاکستری',),'قرمز':('قرمز',),'آبی':('آبی',),'طلایی':('طلایی',),
        'نوک مدادی':('نوک مدادی',),'سبز':('سبز',),'قهوه‌ای':('قهوه ای','قهوه‌ای')}
    for value,patterns in aliases.items():
        if any(re.search(r'(?<!\w)'+re.escape(normalize(q))+r'(?!\w)',t) for q in patterns):return value
    return None
