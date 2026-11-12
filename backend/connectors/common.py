import html, json, re, time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

FA_DIGITS=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')

def norm(v):
    v=html.unescape(str(v or '')).translate(FA_DIGITS).lower().replace('ي','ی').replace('ك','ک').replace('‌',' ')
    v=re.sub(r'[^\w\s\-./,:]+',' ',v)
    return re.sub(r'\s+',' ',v).strip()

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.links=[]; self._href=None; self._txt=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='a':
            self._href=dict(attrs).get('href'); self._txt=[]
    def handle_data(self,data):
        if self._href is not None:self._txt.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=='a' and self._href is not None:
            self.links.append((self._href,re.sub(r'\s+',' ',' '.join(self._txt)).strip()))
            self._href=None; self._txt=[]

class TextParser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_data(self,data):
        d=re.sub(r'\s+',' ',data).strip()
        if d:self.parts.append(d)

def links_from_html(raw,base):
    p=LinkParser();p.feed(raw)
    out=[]
    for href,text in p.links:
        if not href:continue
        out.append((urljoin(base,href),text))
    return out

def text_from_html(raw):
    p=TextParser();p.feed(raw);return ' '.join(p.parts)

def fetch_html(url,timeout=12,max_bytes=3_000_000):
    # Chromium is enabled by default for dynamic marketplace listing pages.
    # `auto` first tries HTML and renders only when it is a JavaScript shell;
    # an access denial is never bypassed through a second transport.
    from .browser import browser_mode, rendered_html
    mode = browser_mode()
    if mode == 'playwright':
        return rendered_html(url, timeout=timeout, max_bytes=max_bytes)
    if mode == 'auto':
        try:
            raw = _fetch_http_html(url, timeout=timeout, max_bytes=max_bytes)
        except RuntimeError as exc:
            if any(key in str(exc) for key in ('401', '403', '429')):
                raise
            return rendered_html(url, timeout=timeout, max_bytes=max_bytes)
        # Detect JavaScript shells lacking any ad anchor. Ordinary static
        # documents stay on the fast HTTP path.
        if len(raw) < 2500 and ('id="__next"' in raw or 'id="root"' in raw or 'enable javascript' in raw.lower()):
            return rendered_html(url, timeout=timeout, max_bytes=max_bytes)
        return raw
    return _fetch_http_html(url, timeout=timeout, max_bytes=max_bytes)


def _fetch_http_html(url,timeout=12,max_bytes=3_000_000):
    req=Request(url,headers={
        'User-Agent':'Mozilla/5.0 (compatible; DavoodiCarMarket/1.0; +https://davoodicar.liara.run)',
        'Accept':'text/html,application/xhtml+xml',
        'Accept-Language':'fa-IR,fa;q=0.9,en;q=0.5',
        'Cache-Control':'no-cache',
    })
    try:
        with urlopen(req,timeout=timeout) as r:
            ct=(r.headers.get('Content-Type') or '').lower()
            if 'html' not in ct and 'text' not in ct:raise RuntimeError('پاسخ HTML نیست')
            data=r.read(max_bytes+1)
            if len(data)>max_bytes:raise RuntimeError('صفحه بیش از حد بزرگ است')
            enc='utf-8'
            m=re.search(r'charset=([\w-]+)',ct)
            if m:enc=m.group(1)
            return data.decode(enc,errors='replace')
    except HTTPError as e:
        if e.code in (401,403):raise RuntimeError(f'دسترسی عمومی سایت رد شد ({e.code})')
        if e.code==429:raise RuntimeError('محدودیت 429 از سایت')
        raise RuntimeError(f'خطای HTTP {e.code}')
    except (URLError,TimeoutError) as e:
        raise RuntimeError('ارتباط با سایت برقرار نشد') from e

def same_host(url,domain):
    h=(urlparse(url).hostname or '').lower().removeprefix('www.')
    return h==domain or h.endswith('.'+domain)

def token_score(brand,model,text):
    t=norm(text); toks=[]
    for x in (brand,model):
        toks += [z for z in re.findall(r'[\wآ-ی]+',norm(x)) if len(z)>1]
    if not toks:return 0
    return sum(1 for z in set(toks) if z in t)/len(set(toks))

def matches_model(brand,model,text,minimum=.6):
    # Most public ads show the model but omit the manufacturer name.
    # Only model tokens are mandatory; main's evidence scorer later checks
    # year, trim, mileage, body and other requested fields.
    if model:return token_score('',model,text)>=minimum
    return token_score(brand,'',text)>=.3

def explicit_price(text):
    # Do not take the first number on a page: it may be a seller fee, loan,
    # unrelated sidebar ad, or installment. Ambiguous prices abstain.
    from safety_v24 import explicit_vehicle_price
    return explicit_vehicle_price(text)

def year_value(text):
    t=norm(text)
    for m in re.finditer(r'(?<!\d)(13\d{2}|14\d{2}|19\d{2}|20\d{2})(?!\d)',t):
        v=int(m.group(1))
        if 1350<=v<=1450 or 1950<=v<=2035:return v
    return None

def mileage_value(text):
    from safety_v24 import mileage_from_description
    return mileage_from_description(text)

# Structured-data extraction only from an individual, public listing detail page.
# Unknown schema or currency is never interpreted as an asking price.
def listing_metadata(raw):
    import json
    from datetime import datetime
    from safety_v24 import explicit_vehicle_price, mileage_from_description
    data={'price':None,'published_at':None,'mileage':None,'year':None}
    blocks=re.findall(r'<script[^>]*type=[\'\"]application/ld\+json[\'\"][^>]*>(.*?)</script>',raw,re.I|re.S)
    def walk(obj):
        if isinstance(obj,list):
            for x in obj:yield from walk(x)
        elif isinstance(obj,dict):
            yield obj
            for k in ('@graph','itemListElement','mainEntity'):
                if k in obj:yield from walk(obj[k])
    for block in blocks[:12]:
        try: obj=json.loads(html.unescape(block.strip()))
        except (ValueError,TypeError):continue
        for record in walk(obj):
            typ=record.get('@type') or ''
            if isinstance(typ,list):typ=' '.join(map(str,typ))
            if not any(x in str(typ).lower() for x in ('product','vehicle','car','individualproduct','offer')):
                continue
            offer=record.get('offers') or record
            if isinstance(offer,list):offer=offer[0] if offer else {}
            if isinstance(offer,dict) and data['price'] is None:
                money=offer.get('price')
                currency=str(offer.get('priceCurrency') or '').upper()
                if money is not None and currency in ('IRR','IRT','TOMAN'):
                    try:
                        amount=float(str(money).replace(',','').translate(FA_DIGITS))
                        amount=round(amount/10) if currency=='IRR' else round(amount)
                        if 50_000_000<=amount<=100_000_000_000:data['price']=amount
                    except (ValueError,TypeError):pass
            for obj in (record,offer):
                if not isinstance(obj,dict):continue
                if not data['published_at']:
                    for key in ('datePosted','datePublished','dateCreated'):
                        if obj.get(key):data['published_at']=obj[key];break
                if data['mileage'] is None:
                    dist=obj.get('mileageFromOdometer') or obj.get('mileage')
                    if isinstance(dist,dict):dist=dist.get('value')
                    if dist is not None:
                        try:
                            val=int(str(dist).replace(',','').translate(FA_DIGITS))
                            if 0<=val<=2_000_000:data['mileage']=val
                        except (TypeError,ValueError):pass
    return data
