"""Davoodi Car evidence assessment and transparent, non-generative pricing.

Scores are heuristic quality indicators (0-100), NOT probabilities that a price
is correct. No remote calls are made here. Dates represent *listing publication*
not the time a search engine saw a page.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
import statistics
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
EDITORIAL = ('article', 'editorial', 'news', 'guide', 'category', 'unknown')


def norm(value):
    value = str(value or '').translate(_DIGITS).casefold().replace('ي', 'ی').replace('ك', 'ک').replace('‌', ' ')
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]+', ' ', value)).strip()


def canonical_url(url):
    try:
        u = urlsplit(str(url or '').strip())
        if u.scheme not in ('https', 'http') or not u.hostname:
            return ''
        q = sorted((k, v) for k, v in parse_qsl(u.query) if not (k.lower().startswith('utm_') or k.lower() in ('ref', 'source', 'fbclid', 'gclid')))
        return urlunsplit((u.scheme.lower(), u.netloc.lower().removeprefix('www.'), u.path.rstrip('/'), urlencode(q), ''))
    except ValueError:
        return ''


def parse_timestamp(value):
    """Parse publication dates (unix secs or ISO strings); never infer from observed_at."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if value > 10**12:
            value /= 1000
        return float(value) if 946684800 <= value <= 4102444800 else None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
            if dt.tzinfo is None:
                return None  # No timezone; avoid guessing the date precision.
            return dt.timestamp()
        except (ValueError, OverflowError):
            return None
    return None


def compatible_year(requested, observed):
    """Return True/False/None. Gregorian to Jalali is ambiguous at Nowruz."""
    if not isinstance(requested, int) or not isinstance(observed, int):
        return None
    if requested == observed:
        return True
    if (requested < 1500) == (observed < 1500):
        return False
    solar = requested if requested < 1500 else observed
    gregorian = requested if requested >= 1500 else observed
    if solar in (gregorian - 621, gregorian - 622):
        return None  # Possible same year; unresolved without month/day.
    return False


def _token_coverage(needle, text):
    tokens = [t for t in norm(needle).split() if len(t) >= 2 or t.isdigit()]
    if not tokens:
        return None
    words = set(norm(text).split())
    return sum(t in words for t in tokens) / len(tokens)


def score_evidence(item, vehicle, *, now=None, max_age_days=60):
    """Return quality score and hard-rejection reason for each candidate."""
    now = now or datetime.now(timezone.utc).timestamp()
    kind = str(item.get('kind') or '')
    title = str(item.get('title') or '')
    description = str(item.get('content') or '')
    text = title + ' ' + description
    price = item.get('price')
    if kind not in ('listing', 'market_price'):
        return 0, 'این صفحه آگهی فروش یا مرجع قیمت نیست'
    if not isinstance(price, (int, float)) or isinstance(price, bool) or not 50_000_000 <= price <= 100_000_000_000:
        return 0, 'قیمت قابل استناد در صفحه وجود ندارد'
    if not canonical_url(item.get('url')):
        return 0, 'لینک معتبر نیست'
    model_cov = _token_coverage(vehicle.get('model'), text)
    brand_cov = _token_coverage(vehicle.get('brand'), text)
    # Brand in a model's text is not mandatory, but the requested model must match.
    if model_cov is not None and model_cov < .80:
        from vehicle_nlp import identify_vehicle
        detected = identify_vehicle(text)
        if detected and norm(detected.get('model')) == norm(vehicle.get('model')):
            model_cov = 1
        else:
            return 0, 'مدل خودرو با درخواست تطابق ندارد'
    requested_year=vehicle.get('year')
    observed_year=item.get('year')
    year_status=compatible_year(requested_year, observed_year)
    if requested_year is not None and observed_year is None:
        return 0, 'سال انتشار/مدل آگهی مشخص نیست؛ نیازمند تأیید کارشناس'
    if year_status is False:
        return 0, 'سال تولید با درخواست متفاوت است'
    if requested_year is not None and year_status is None:
        return 0, 'معادل سال شمسی/میلادی قطعی نیست؛ نیازمند تأیید کارشناس'
    pub=parse_timestamp(item.get('published_at'))
    age=(now-pub)/86400 if pub is not None else None
    if age is not None and (age > max_age_days or age < -1):
        return 0, 'آگهی قدیمی یا دارای تاریخ نامعتبر است'
    if age is None:
        return 0, 'تاریخ انتشار آگهی نامعلوم است؛ نیازمند تأیید کارشناس'
    request_trim=norm(vehicle.get('trim'))
    item_trim=norm(item.get('trim'))
    if request_trim and not item_trim:
        return 0, 'تیپ آگهی نامعلوم است؛ نیازمند تأیید کارشناس'
    if request_trim and request_trim!=item_trim:
        return 0, 'تیپ خودرو متفاوت است'
    req_transmission=norm(vehicle.get('transmission'))
    listed_transmission=norm(item.get('transmission'))
    if req_transmission and req_transmission not in ('نامشخص','unknown'):
        if not listed_transmission:
            return 0, 'گیربکس آگهی مشخص نیست؛ نیازمند تأیید کارشناس'
        if req_transmission!=listed_transmission:
            return 0, 'نوع گیربکس خودرو متفاوت است'
    req_condition=norm(vehicle.get('condition'))
    listed_condition=norm(item.get('condition'))
    if req_condition and req_condition not in ('نامشخص','unknown','تعیین نشده','صفر کیلومتر','نو','صفر'):
        if not listed_condition:
            return 0, 'وضعیت بدنه آگهی مشخص نیست؛ نیازمند تأیید کارشناس'
        if req_condition=='بدون رنگ' and listed_condition!='بدون رنگ':
            return 0, 'وضعیت بدنه آگهی با خودروی درخواستی متفاوت است'
        if req_condition!='بدون رنگ' and listed_condition=='بدون رنگ':
            return 0, 'آگهی سالم برای خودروی دارای آسیب بدنه قابل قیاس دقیق نیست'
        # Both descriptions mention damage, but not necessarily the same parts.
        # Do not invent a percentage adjustment for unknown panel/repair differences.
        if req_condition!='بدون رنگ' and listed_condition!=req_condition:
            return 0, 'نوع یا محل آسیب بدنه متفاوت/نامشخص است؛ نیازمند بررسی'
    request_mileage=vehicle.get('mileage')
    observed_mileage=item.get('mileage')
    if item.get('is_new') and isinstance(observed_mileage,int) and observed_mileage>0:
        return 0, 'تعارض صفر کیلومتر و کارکرد ثبت شده در آگهی'
    if request_mileage == 0 and not item.get('is_new'):
        return 0, 'صفر کیلومتر بودن آگهی تأیید نشده است'
    if request_mileage == 0 and observed_mileage not in (0,None):
        return 0, 'خودروی کارکرده در استعلام خودروی صفر'
    if isinstance(request_mileage,int) and request_mileage>0:
        if item.get('is_new'):
            return 0, 'خودروی صفر در استعلام کارکرده'
        if observed_mileage is None:
            return 0, 'کارکرد آگهی مشخص نیست؛ نیازمند تأیید کارشناس'
        if abs(request_mileage-observed_mileage)>max(20000,request_mileage*.4):
            return 0, 'کارکرد آگهی با خودروی درخواستی اختلاف زیاد دارد'
    score = 0.0
    # Max: 30+10+15+10+10+7+10+8 = 100.
    score += 30 * (model_cov if model_cov is not None else .30)
    score += 10 * (brand_cov if brand_cov is not None else .35)
    score += 15 * (1 if year_status is True else .40 if year_status is None else 0)
    score += 10 * (1 if request_trim and request_trim in (item_trim, norm(text)) else .5 if not request_trim else .25)
    if isinstance(request_mileage, int) and isinstance(observed_mileage, int):
        diff = abs(request_mileage - observed_mileage)
        score += 10 * max(.10, 1 - diff / max(60000, request_mileage))
    elif request_mileage is None:
        score += 5
    else:
        score += 2.5
    requested_city = norm(vehicle.get('city'))
    listed_city = norm(item.get('city'))
    score += 7 if requested_city and requested_city == listed_city else 3.5 if not requested_city else 1.5
    if age is None:
        score += 3  # Unknown freshness must not be treated as new.
    else:
        score += 10 * max(.2, 1 - max(age, 0) / max_age_days)
    score += 8 if kind == 'listing' else 4
    return max(0, min(100, round(score))), None


def assess_and_dedupe(items, vehicle, *, now=None, min_score=42, max_age_days=60):
    """Marks accepted/rejected entries; de-duplicates URLs and strong cross-post duplicates.

    Never discard rejects entirely; diagnostics need rejection reasons.
    """
    by_url = set()
    by_fingerprint = set()
    for item in items:
        if item.get('rejection_reason'):
            item['accepted'] = False
            item['quality_score'] = 0
            continue
        score, reason = score_evidence(item, vehicle, now=now, max_age_days=max_age_days)
        item['quality_score'] = score
        item['evidence_tier'] = 'آگهی مستقیم' if item.get('kind') == 'listing' else 'قیمت مرجع' if item.get('kind') == 'market_price' else 'اطلاعاتی'
        item['review_required'] = bool(reason and ('نامعلوم' in reason or 'نیازمند' in reason or 'مشخص نیست' in reason or 'قطعی نیست' in reason))
        item['accepted'] = not reason and score >= min_score
        item['rejection_reason'] = reason or ('امتیاز تطابق و اعتبار کافی نیست' if score < min_score else None)
        if not item['accepted']:
            continue
        canonical = canonical_url(item.get('url'))
        title = norm(item.get('title'))
        fingerprint = (norm(item.get('domain')), title, item.get('price'), item.get('mileage'), norm(item.get('city')))
        # Cross-site duplication requires strongly matching title + price + mileage + city.
        strong_fp = (title, item.get('price'), item.get('mileage'), norm(item.get('city'))) if len(title) > 22 and item.get('mileage') is not None and item.get('city') else None
        if canonical in by_url or (strong_fp is not None and strong_fp in by_fingerprint):
            item['accepted'] = False
            item['rejection_reason'] = 'آگهی تکراری'
        else:
            by_url.add(canonical)
            if strong_fp:
                by_fingerprint.add(strong_fp)
    return items


def _histogram(prices, bins=5):
    if not prices:
        return []
    low = min(prices)
    high = max(prices)
    if low == high:
        return [{'min': low, 'max': high, 'count': len(prices)}]
    size = (high - low) / bins
    counts = [0] * bins
    for p in prices:
        counts[min(bins - 1, int((p - low) / size))] += 1
    return [{'min': round(low + i * size), 'max': round(low + (i + 1) * size), 'count': c} for i, c in enumerate(counts)]


def price_summary(items, target_mileage=None):
    """Evidence-weighted market quote, with transparent sample-size safeguards."""
    priced = [x for x in items if x.get('accepted') and isinstance(x.get('price'), (int, float)) and x.get('kind') in ('listing', 'market_price')]
    empty = {'price_min':None, 'price_max':None, 'price_average':None, 'price_median':None,
             'suggested_min':None, 'suggested_max':None, 'confidence':'کم', 'confidence_score':0,
             'confidence_is_probability':False, 'source_count':0,'domain_count':0,'sample_count':0,
             'listing_count':0,'reference_count':0,'limited_evidence':False,
             'used_source_urls':[],'observed_prices':[],'histogram':[],'outliers_removed':0,
             'pricing_note':'نمونه قیمت‌دار قابل استناد پیدا نشد.'}
    if not priced:
        return empty
    # Outlier rules apply only with >=4 observations, and never force a fake 3-sample mean.
    outliers = []
    clean = list(priced)
    if len(priced) >= 3:
        median = statistics.median(x['price'] for x in priced)
        mad = statistics.median(abs(x['price'] - median) for x in priced)
        threshold = max(3 * mad, .22 * median)
        outliers = [x for x in priced if abs(x['price'] - median) > threshold]
        clean = [x for x in priced if x not in outliers]
    if not clean:
        return {**empty, 'outliers_removed':len(outliers)}
    prices = sorted(int(x['price']) for x in clean)
    listing_count = sum(x.get('kind') == 'listing' for x in clean)
    reference_count = sum(x.get('kind') == 'market_price' for x in clean)
    domains = len(set(x.get('domain') for x in clean))
    valid_estimate = len(clean) >= 3 and listing_count >= 2 and domains >= 2
    # Keep references as modest supporting data but never let references alone
    # create a market quote. Charts and raw values remain available.
    weights=[]
    for x in clean:
        weight = max(.2, (x.get('quality_score', 50) / 100))
        weight *= 1.0 if x.get('kind') == 'listing' else .45
        if isinstance(target_mileage, int) and isinstance(x.get('mileage'), int):
            weight *= max(.25, 1 - abs(x['mileage'] - target_mileage) / max(target_mileage, 50000))
        weights.append(weight)
    weighted = round(sum(x['price'] * w for x,w in zip(clean,weights)) / sum(weights)) if valid_estimate else None
    # Confidence is a heuristic data-quality score, NOT a calibrated probability.
    quality = statistics.mean(x.get('quality_score', 50) for x in clean)
    coverage = min(1, len(clean) / 8)
    diversity = min(1, domains / 3)
    listing_share = listing_count / len(clean)
    confidence_score = round(min(98, .40 * quality + 25 * coverage + 20 * diversity + 15 * listing_share))
    if not valid_estimate:
        confidence_score = min(49, confidence_score)
    level = 'زیاد' if valid_estimate and confidence_score >= 80 else 'متوسط' if valid_estimate and confidence_score >= 60 else 'کم'
    return {
        **empty,
        'price_min': prices[0], 'price_max':prices[-1],
        'price_median':round(statistics.median(prices)) if valid_estimate else None,
        'price_average':weighted,
        'suggested_min': prices[max(0, math.floor((len(prices)-1)*.25))] if valid_estimate else None,
        'suggested_max': prices[min(len(prices)-1, math.ceil((len(prices)-1)*.75))] if valid_estimate else None,
        'sample_count':len(clean), 'listing_count':listing_count,'reference_count':reference_count,
        'source_count':len(set(canonical_url(x['url']) for x in clean)), 'domain_count':domains,
        'confidence':level, 'confidence_score':confidence_score,
        'limited_evidence':not valid_estimate,
        'used_source_urls':[x['url'] for x in clean],
        'observed_prices':prices, 'histogram':_histogram(prices),
        'outliers_removed':len(outliers),
        'pricing_note':('برآورد از آگهی‌های معتبر با وزن کمتر برای قیمت مرجع. امتیاز اطمینان، شاخص کیفیت داده است و احتمال آماری نیست.'
                        if valid_estimate else 'شواهد محدود: برای برآورد دست‌کم ۳ شاهد تأییدشده، ۲ آگهی فروش و ۲ سایت مستقل لازم است.')
    }
