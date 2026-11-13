"""Conservative quality gates for v30.8 vehicle adverts and grouped prices.

Never infer missing money units or replace unknown years/trim/mileage with guesses.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import statistics

_DIGITS=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')

def _norm(v):
    return ' '.join(str(v or '').translate(_DIGITS).replace('ي','ی').replace('ك','ک').replace('‌',' ').casefold().split())

def detail_conflict(card,detail):
    """Decline a listing when card and detail provide contradictory facts."""
    if not isinstance(card,dict) or not isinstance(detail,dict):return 'INVALID_EVIDENCE'
    for field,err in (('year','YEAR_CONFLICT'),('mileage','MILEAGE_CONFLICT'),('price','PRICE_CONFLICT')):
        a,b=card.get(field),detail.get(field)
        if a is None or b is None:continue
        try:
            if isinstance(a,bool) or isinstance(b,bool):return 'INVALID_'+field.upper()
            av,bv=int(a),int(b)
        except (TypeError,ValueError):return 'INVALID_'+field.upper()
        if field=='year' and av!=bv:return err
        if field=='mileage' and abs(av-bv)>max(1000,max(av,bv)*0.02):return err
        if field=='price' and (min(av,bv)<=0 or abs(av-bv)>max(50_000_000,max(av,bv)*0.05)):return err
    return None

def explicit_price_matches(price,text):
    """Only accept asking-price amounts present in the actual local ad text.

    A 'Toman' string from an unrelated commission/fee is insufficient.
    """
    from safety_v24 import explicit_vehicle_price
    if isinstance(price,bool):return False
    try:amount=int(price)
    except (TypeError,ValueError):return False
    if not 50_000_000<=amount<=100_000_000_000:return False
    evidence=_norm(text)
    if 'تومان' not in evidence:return False
    if any(x in evidence for x in ('قیمت توافقی','تماس بگیرید','قیمت کارخانه','قیمت نمایندگی')):
        return False
    # The existence of a separate Toman-denominated fee does not validate a
    # Rial-denominated listing price. Remove Rial clauses before price matching.
    from re import sub
    toman_only=sub(r'(?<!\\d)\\d{8,16}\\s*ریال',' ',evidence)
    described=explicit_vehicle_price(toman_only)
    return described is not None and abs(amount-described)<=max(1_000_000,int(amount*.01))

def price_outliers(rows,*,min_rows=7):
    """Remove only obvious within-segment price parser/currency outliers.

    Return (retained,rejected). Do not filter sparse segments.
    """
    clean=[]
    for row in rows:
        try:
            if isinstance(row.get('price_toman'),bool):continue
            v=int(row.get('price_toman',0))
            if 50_000_000<=v<=100_000_000_000:clean.append(row)
        except (ValueError,TypeError):continue
    if len(clean)<min_rows:return clean,[]
    prices=[int(row['price_toman']) for row in clean]
    median=statistics.median(prices)
    mad=statistics.median(abs(p-median) for p in prices)
    spread=max(median*0.45,mad*6,100_000_000)
    keep=[];excluded=[]
    for row in clean:
        (keep if abs(int(row['price_toman'])-median)<=spread else excluded).append(row)
    return keep,excluded

def publication_age(value,now=None):
    """Missing publication date is UNKNOWN, not recent."""
    if not value:return 'unknown'
    if isinstance(value,datetime):dt=value
    else:
        try:dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        except (TypeError,ValueError):return 'invalid'
    if dt.tzinfo is None:return 'invalid'
    now=now or datetime.now(timezone.utc)
    if dt>now+timedelta(hours=1):return 'future'
    if dt<now-timedelta(days=14):return 'stale'
    return 'fresh'

def source_cooldown(error_code,last_attempt,now=None,hours=6):
    """Avoid re-querying a source for hours after explicit access rejection."""
    if error_code not in ('HTTP_403','HTTP_429','CAPTCHA_OR_CHALLENGE'):return False
    if not isinstance(last_attempt,datetime) or last_attempt.tzinfo is None:return False
    try:window=max(0,min(24,int(hours)))
    except (TypeError,ValueError):window=6
    if not window:return False
    now=now or datetime.now(timezone.utc)
    return last_attempt<=now and now-last_attempt<timedelta(hours=window)
