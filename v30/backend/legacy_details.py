"""Collect verifiable, non-contact fields from an individual public car ad.

Photos and descriptions are stored as source pointers/evidence only. Personal
phone numbers, seller identities and email addresses are not collected.
Unknown fields remain absent. Every URL is linked to its original ad.
"""
from __future__ import annotations
import re
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from .domain import normalize

_FA=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')
COLORS=('سفید','مشکی','نقره‌ای','نقره ای','خاکستری','نوک مدادی',
        'آبی','قرمز','قهوه‌ای','قهوه ای','زرد','سبز','طلایی','بژ',
        'یشمی','سرمه‌ای')
CITIES=('تهران','کرج','مشهد','اصفهان','شیراز','تبریز','اهواز','قم','رشت',
        'یزد','کرمان','اراک','قزوین','اردبیل','ساری','بندرعباس','سنندج')

def _safe_external_image(src,base):
    url=urljoin(base,str(src or '').strip())
    try:
        u=urlsplit(url)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
            return None
        if len(url)>800:return None
        return url
    except ValueError:return None

def extract_public_features(raw,url):
    if not raw:return {}
    soup=BeautifulSoup(raw[:2_000_000],'html.parser')
    for tag in soup.select('script,style,noscript,svg'):tag.decompose()
    main=soup.select_one('main,article,[role="main"]') or soup.body or soup
    text=re.sub(r'\s+',' ',main.get_text(' ',strip=True))[:4000]
    normed=normalize(text)
    fields={}
    color_match=re.search(r'(?:رنگ\s*(?:بدنه|خودرو)?\s*[:：]?\s*)('+('|'.join(map(re.escape,COLORS))+r')\b',normed)
    if color_match:fields['body_color']=color_match.group(1)
    city_match=re.search(r'(?:شهر|موقعیت|محل\s*بازدید)\s*[:：]?\s*('+('|'.join(CITIES))+r')\b',normed)
    if city_match:fields['city']=city_match.group(1)
    images=[]
    for tag in soup.select('meta[property="og:image"],meta[name="twitter:image"],main img[src],article img[src],img[itemprop="image"]'):
        src=tag.get('content') if tag.name=='meta' else tag.get('src') or tag.get('data-src')
        dest=_safe_external_image(src,url)
        if dest and dest not in images:images.append(dest)
        if len(images)>=12:break
    if images:fields['photo_urls']=images
    # A sanitized excerpt is useful for auditing parsing, but must not
    # retain contact numbers, email addresses or instant messenger handles.
    snippet=re.sub(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}','[email]',text[:1400])
    snippet=re.sub(r'(?<!\d)[+۰-۹٠-٩0-9()\s-]{10,20}(?!\d)','[phone]',snippet)
    if snippet:fields['public_description_excerpt']=snippet[:1000]
    return fields
