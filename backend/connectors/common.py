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

def fetch_html(url,timeout=12,max_bytes=2_000_000):
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

def explicit_price(text):
    # Shared conservative parser; do not accidentally choose commission as price.
    from market_parsers import parse_price
    return parse_price(text)

def year_value(text):
    t=norm(text)
    for m in re.finditer(r'(?<!\d)(13\d{2}|14\d{2}|19\d{2}|20\d{2})(?!\d)',t):
        v=int(m.group(1))
        if 1350<=v<=1450 or 1950<=v<=2035:return v
    return None

def mileage_value(text):
    t=norm(text).replace(',','').replace('٬','')
    if re.search(r'صفر\s*کیلومتر',t):return 0
    for pat in [r'کارکرد\s*[:\-]?\s*(\d{1,7})\s*(?:کیلومتر|km)?',r'(?<!\d)(\d{1,7})\s*(?:کیلومتر|km)']:
        m=re.search(pat,t)
        if m:
            v=int(m.group(1))
            if 0<=v<=2_000_000:return v
    return None

# v24: Read only structured, explicitly published metadata from public pages.
# Crawling date != publication date; never fabricate listing freshness.
def structured_listing_fields(raw):
    from market_parsers import publication_date, parse_price, parse_mileage
    from html.parser import HTMLParser
    class Metadata(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.in_ld=False;self.buffer=[];self.scripts=[];self.metadata={}
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='script' and 'ld+json' in a.get('type','').lower():
                self.in_ld=True;self.buffer=[]
            if tag=='meta':
                name=(a.get('property') or a.get('name') or a.get('itemprop') or '').lower()
                if name in ('article:published_time','datepublished','dateposted','product:release_date'):
                    self.metadata[name]=a.get('content','')
            if tag=='time' and a.get('datetime'):
                self.metadata['time']=a['datetime']
        def handle_data(self,data):
            if self.in_ld:self.buffer.append(data)
        def handle_endtag(self,tag):
            if tag=='script' and self.in_ld:
                self.scripts.append(''.join(self.buffer));self.in_ld=False
    p=Metadata()
    try:p.feed(raw[:2_000_000])
    except Exception:return {}
    nodes=[]
    def traverse(data,depth=0):
        if depth>5:return
        if isinstance(data,list):
            for e in data:traverse(e,depth+1)
        elif isinstance(data,dict):
            nodes.append(data)
            for k in ('@graph','mainEntity','itemOffered','offers'):
                if k in data:traverse(data[k],depth+1)
    for block in p.scripts:
        try: traverse(json.loads(html.unescape(block)))
        except (json.JSONDecodeError,ValueError): pass
    result={}
    for node in nodes:
        if not result.get('published_at'):
            for key in ('datePosted','datePublished','dateCreated','uploadDate'):
                if node.get(key):
                    parsed=publication_date(node[key])
                    if parsed:result['published_at']=parsed;break
        if not result.get('price') and node.get('@type') in ('Offer','AggregateOffer'):
            v=node.get('price') or node.get('lowPrice')
            unit=str(node.get('priceCurrency') or '').upper()
            if isinstance(v,(str,int,float)) and v:
                raw_value=str(v).replace(',','').translate(FA_DIGITS).strip()
                if re.fullmatch(r'\d+(?:\.\d+)?',raw_value):
                    amount=float(raw_value)
                    if unit=='IRR':amount/=10
                    # Prices without an explicit currency cannot be normalized reliably.
                    if unit in ('IRR','IRT','TOMAN') and 50_000_000<=amount<=100_000_000_000:
                        result['price']=round(amount)
    if not result.get('published_at'):
        for value in p.metadata.values():
            parsed=publication_date(value)
            if parsed:result['published_at']=parsed;break
    return result
