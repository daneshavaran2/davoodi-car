import os, json, time, hmac, hashlib, base64, re, asyncio, logging, threading, random, sqlite3, statistics
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from fastapi import FastAPI, HTTPException, Depends, Header, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from connectors import run as run_builtin_connector
from market_intelligence import assess_and_dedupe, price_summary
from model_overview import name_only_search, model_overview
from vehicle_nlp import identify_vehicle, generation_from_text, variant_from_text
from safety_v24 import explicit_vehicle_price, mileage_from_description, new_status, body_group, trim_status

logging.basicConfig(level=logging.INFO)
app = FastAPI(title='Davoodi Car')
PASSWORD = os.getenv('ADMIN_PASSWORD','')
SECRET = os.getenv('SESSION_SECRET','')
AVALAI_KEY = os.getenv('AVALAI_API_KEY','')
OPENAI_KEY = os.getenv('OPENAI_API_KEY','')
OPENAI_MODEL = os.getenv('OPENAI_MODEL','gpt-4.1-mini')
CACHE_TTL = int(os.getenv('SEARCH_CACHE_TTL', '900'))
EMPTY_RESULT_CACHE_TTL = min(120,max(0,int(os.getenv('EMPTY_RESULT_CACHE_TTL','45'))))
DB_PATH = os.getenv('DB_PATH','/app/data/davoodi.db')
MAX_SEARCHES_PER_HOUR = int(os.getenv('MAX_SEARCHES_PER_HOUR','30'))
SEARCH_COOLDOWN = int(os.getenv('SEARCH_COOLDOWN','12'))
DOMAIN_CACHE_TTL = int(os.getenv('DOMAIN_CACHE_TTL','21600'))
SEARCH_REQUEST_DELAY = float(os.getenv('SEARCH_REQUEST_DELAY','0'))
MAX_DOMAIN_REQUESTS = min(10,max(1,int(os.getenv('MAX_DOMAIN_REQUESTS','6'))))
MAX_STALE_AGE = min(86400,max(CACHE_TTL,int(os.getenv('MAX_STALE_AGE_SECONDS','3600'))))
_rate_lock = threading.Lock()
_recent_calls = []
_last_search = [0.0]
_last_search_by_client={}
_recent_calls_by_client={}

_cache = {}
_cache_lock = threading.Lock()
_search_semaphore = threading.BoundedSemaphore(max(1,min(8,int(os.getenv('MAX_CONCURRENT_SEARCHES','3')))))
if not PASSWORD or not SECRET or len(SECRET)<32:
    raise RuntimeError('Set ADMIN_PASSWORD and SESSION_SECRET (32+ characters) in Liara environment')

_progress_lock=threading.Lock()
_progress={}
_progress_ctx=threading.local()

def progress_report(stage, done=0, total=0, site=None):
    job=getattr(_progress_ctx,'id',None)
    if not job:return
    now=time.time()
    with _progress_lock:
        if len(_progress)>250:
            for key in sorted(_progress,key=lambda j:_progress[j].get('updated_at',0))[:60]:
                _progress.pop(key,None)
        old=_progress.get(job,{})
        _progress[job]={'stage':stage,'done':done,'total':total,'site':site,
                        'started_at':old.get('started_at',now),'updated_at':now}

def sign(value): return hmac.new(SECRET.encode(),value.encode(),hashlib.sha256).hexdigest()
def make_token():
    value=str(int(time.time())+8*3600)
    return value+'.'+sign(value)
def authorized(authorization: str|None=Header(default=None)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'ابتدا وارد شوید')
    token=authorization[7:]
    try:
        expiry,signature=token.split('.',1)
        valid=int(expiry)>time.time() and hmac.compare_digest(sign(expiry),signature)
    except (ValueError,TypeError): valid=False
    if not valid: raise HTTPException(401,'نشست منقضی شده است')
    return True
@app.get('/api/search-progress/{request_id}')
def get_progress(request_id:str,_=Depends(authorized)):
    if len(request_id)>64 or not re.fullmatch(r'[a-zA-Z0-9-]+',request_id):
        raise HTTPException(400,'شناسه درخواست معتبر نیست')
    with _progress_lock:
        state=_progress.get(request_id)
        if state and time.time()-state['updated_at']<=180:
            return dict(state)
    return {'stage':'waiting','done':0,'total':0}

class Login(BaseModel): password: str
class Search(BaseModel):
    query: str=Field(min_length=2,max_length=180)
    brand: str|None=None
    model: str|None=None
    year: int|None=Field(default=None,ge=1350,le=2100)
    mileage: int|None=Field(default=None,ge=0,le=2000000)
    condition: str|None=None
    transmission: str|None=None
    color: str|None=None
    trim: str|None=None
    city: str|None=None
    refresh: bool=False
    request_id: str|None=Field(default=None, min_length=16, max_length=64, pattern=r'^[a-zA-Z0-9-]+$')
class CompareInput(BaseModel):
    ids: list[int]=Field(min_length=2,max_length=3)
class _ManagedConnection(sqlite3.Connection):
    """Ensure SQLite file handles are closed on every context-manager exit."""
    def __exit__(self, typ, value, traceback):
        try:
            return super().__exit__(typ, value, traceback)
        finally:
            self.close()

def db():
    Path(DB_PATH).parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=15,factory=_ManagedConnection)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA busy_timeout=15000')
    c.execute('CREATE TABLE IF NOT EXISTS searches(id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, cache_key TEXT NOT NULL, result_json TEXT NOT NULL, created_at REAL NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS domain_cache(cache_key TEXT PRIMARY KEY, result_json TEXT NOT NULL, created_at REAL NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_search_key ON searches(cache_key, created_at DESC)')
    c.commit()
    return c
def saved(key,age=None):
    with db() as c:
        row=c.execute('SELECT * FROM searches WHERE cache_key=? ORDER BY created_at DESC LIMIT 1',(key,)).fetchone()
    if not row or (age is not None and time.time()-row['created_at']>age): return None
    return {'value':json.loads(row['result_json']),'at':row['created_at'],'id':row['id']}
def persist(query,key,value):
    with db() as c:
        cur=c.execute('INSERT INTO searches(query,cache_key,result_json,created_at) VALUES(?,?,?,?)',(query,key,json.dumps(value,ensure_ascii=False),time.time()))
        c.execute('DELETE FROM searches WHERE id NOT IN (SELECT MAX(id) FROM searches GROUP BY cache_key) AND created_at < ?', (time.time()-30*86400,))
        c.commit()
        return cur.lastrowid
def domain_saved(key,age):
    with db() as c:
        row=c.execute('SELECT result_json,created_at FROM domain_cache WHERE cache_key=?',(key,)).fetchone()
    if not row or time.time()-row['created_at']>age:return None
    return json.loads(row['result_json'])
def domain_persist(key,value):
    with db() as c:
        c.execute('INSERT OR REPLACE INTO domain_cache(cache_key,result_json,created_at) VALUES(?,?,?)',(key,json.dumps(value,ensure_ascii=False),time.time()))
        c.commit()

FA_DIGITS=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')
UNITS={'صفر':0,'یک':1,'يه':1,'دو':2,'سه':3,'چهار':4,'پنج':5,'شش':6,'شیش':6,'هفت':7,'هشت':8,'نه':9,'ده':10,'یازده':11,'دوازده':12,'سیزده':13,'چهارده':14,'پانزده':15,'شانزده':16,'هفده':17,'هجده':18,'نوزده':19}
TENS={'بیست':20,'سی':30,'چهل':40,'پنجاه':50,'شصت':60,'هفتاد':70,'هشتاد':80,'نود':90}
HUNDREDS={'صد':100,'یکصد':100,'دویست':200,'سیصد':300,'چهارصد':400,'پانصد':500,'ششصد':600,'هفتصد':700,'هشتصد':800,'نهصد':900}

def spoken_number(words):
    total=0; group=0;found=False
    for word in words:
        if word=='و':continue
        if word.isdigit(): group+=int(word);found=True
        elif word in UNITS:group+=UNITS[word];found=True
        elif word in TENS:group+=TENS[word];found=True
        elif word in HUNDREDS:group+=HUNDREDS[word];found=True
        elif word in ('هزار','هزارتا'):
            total+=(group or 1)*1000;group=0;found=True
        elif word in ('میلیون',):total+=(group or 1)*1000000;group=0;found=True
        else:return None
    return total+group if found else None


# Dynamic catalog: SQLite persistence survives app restarts only if DB_PATH is on a persistent volume.
def norm_vehicle(value):
    value=str(value or '').lower().translate(FA_DIGITS).replace('ي','ی').replace('ك','ک').replace('‌',' ')
    value=re.sub(r'[^\w\s]',' ',value)
    return re.sub(r'\s+',' ',value).strip()

def catalog_db():
    c=db()
    c.execute("CREATE TABLE IF NOT EXISTS vehicle_catalog(id INTEGER PRIMARY KEY AUTOINCREMENT,brand TEXT NOT NULL,model TEXT NOT NULL,trim TEXT NOT NULL DEFAULT '',aliases_json TEXT NOT NULL DEFAULT '[]',source TEXT NOT NULL DEFAULT 'manual',updated_at REAL NOT NULL,UNIQUE(brand,model,trim))")
    c.commit()
    return c

class VehicleItem(BaseModel):
    brand:str=Field(min_length=1,max_length=90)
    model:str=Field(min_length=1,max_length=100)
    trim:str=''
    aliases:list[str]=Field(default_factory=list,max_length=35)
    source:str='manual'
class VehicleImport(BaseModel):
    items:list[VehicleItem]=Field(min_length=1,max_length=3000)

def upsert_vehicles(items):
    with catalog_db() as c:
        for item in items:
            aliases=list(dict.fromkeys(norm_vehicle(x) for x in item.aliases if norm_vehicle(x)))[:35]
            c.execute('INSERT INTO vehicle_catalog(brand,model,trim,aliases_json,source,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(brand,model,trim) DO UPDATE SET aliases_json=excluded.aliases_json,source=excluded.source,updated_at=excluded.updated_at',
              (item.brand.strip(),item.model.strip(),item.trim.strip()[:100],json.dumps(aliases,ensure_ascii=False),item.source.strip()[:80],time.time()))
        c.commit()
    return len(items)


# Automatic catalog discovery: opt-in periodic jobs, source-backed candidates,
# and promotion only when at least two independent sites corroborate a model.
DISCOVERY_ENABLED=os.getenv('AUTO_CATALOG_DISCOVERY','true').lower() in ('1','true','yes')
DISCOVERY_INTERVAL_HOURS=max(12,int(os.getenv('DISCOVERY_INTERVAL_HOURS','24')))
DISCOVERY_BRANDS=[
 'چری','فونیکس','ام وی ام','جک','کی ام سی','چانگان','هاوال','جیلی','بی وای دی',
 'لاماری','فیدلیتی','دیگنیتی','اکستریم','لوکانو','هونگچی','بایک','دانگ فنگ',
 'هیوندای','کیا','جنسیس','سانگ یانگ','بی ام و','مرسدس بنز','تویوتا','لکسوس',
 'رنو','پژو','نیسان','مزدا','هوندا','فولکس واگن','میتسوبیشی','سوزوکی',
 'ایران خودرو','سایپا','بهمن موتور','کرمان موتور'
]
_discovery_lock=threading.Lock()
_discovery_status={'state':'not_started','last_run':None,'checked':0,'promoted':0,'error':None}

def discovery_db():
    c=catalog_db()
    c.execute("""CREATE TABLE IF NOT EXISTS catalog_evidence(
      brand TEXT NOT NULL, model TEXT NOT NULL, domain TEXT NOT NULL,
      url TEXT NOT NULL, observed_at REAL NOT NULL,
      PRIMARY KEY(brand,model,domain,url))""")
    c.commit()
    return c

def _discover_once(brands):
    from urllib.parse import urlparse
    global _discovery_status
    if not AVALAI_KEY or not OPENAI_KEY:
        raise RuntimeError('AVALAI_API_KEY و OPENAI_API_KEY برای کشف خودکار لازم هستند')
    sites=['hamrah-mechanic.com','khodro45.com','divar.ir']
    checked=0; promoted=0; errors=[]
    # Limit requests to avoid 429 and unexpected provider costs.
    for brand in brands[:3]:
        grouped={}
        for domain in sites:
            q=f'site:{domain} "{brand}" مدل خودرو تیپ'
            try:
                data=post_json('https://api.avalai.ir/v1/search/serper-search',
                    {'query':q,'max_results':8,'hl':'fa'},
                    {'Authorization':'Bearer '+AVALAI_KEY},'AvalAI Search')
                checked+=1
            except Exception as exc:
                errors.append(f'{domain}: {str(exc)[:100]}')
                if '429' in str(exc):break
                continue
            rows=[]
            for r in data.get('results',[]):
                if not isinstance(r,dict):continue
                url=str(r.get('url') or r.get('link') or '')
                host=urlparse(url).hostname or ''
                if not url.startswith('https://') or not (host==domain or host.endswith('.'+domain)):continue
                title=str(r.get('title') or '')[:180]
                if not title:continue
                rows.append({'title':title,'url':url})
            if not rows:continue
            # The LLM proposes names only; it is never allowed to promote without independent evidence.
            prompt=('از عنوان‌های نتایج جستجو، فقط نام مدل‌های واقعی خودرو را استخراج کن. '
                    'نام برند را تغییر نده. سال، قیمت، کارکرد، تیپ نامعلوم و کلمات تبلیغاتی را به نام مدل اضافه نکن. '
                    'فقط مدل‌هایی را برگردان که در عنوان صریحاً ذکر شده‌اند. '
                    'پاسخ JSON: {"models":[{"model":"...","url":"..."}]}. '
                    'URL باید دقیقاً یکی از URLهای ورودی باشد. اگر مطمئن نیستی، حذف کن.')
            try:
                ai=post_json('https://api.openai.com/v1/chat/completions',
                    {'model':OPENAI_MODEL,'temperature':0,'response_format':{'type':'json_object'},
                     'messages':[{'role':'system','content':prompt},
                                 {'role':'user','content':json.dumps({'brand':brand,'results':rows},ensure_ascii=False)}]},
                    {'Authorization':'Bearer '+OPENAI_KEY},'OpenAI')
                proposed=json.loads(ai['choices'][0]['message']['content']).get('models',[])
            except Exception as exc:
                errors.append('extract: '+str(exc)[:100]);continue
            valid_urls={r['url']:r['title'] for r in rows}
            for item in proposed[:20] if isinstance(proposed,list) else []:
                if not isinstance(item,dict):continue
                model=norm_vehicle(item.get('model',''))
                url=str(item.get('url',''))
                if not (3<=len(model)<=65 and url in valid_urls):continue
                if re.search(r'\b(?:قیمت|فروش|خرید|مدل\s*(?:13|14|19|20)\d{2}|تومان|کارکرد)\b',model):continue
                # No promotion from generic headings or a model absent from the source title.
                normalized_title=norm_vehicle(valid_urls[url])
                if not all(part in normalized_title for part in model.split()):continue
                grouped.setdefault(model,{})[domain]=url
            time.sleep(max(1,float(os.getenv('DISCOVERY_REQUEST_DELAY','2'))))
        with discovery_db() as c:
            for model,by_domain in grouped.items():
                for domain,url in by_domain.items():
                    c.execute('INSERT OR REPLACE INTO catalog_evidence VALUES(?,?,?,?,?)',
                              (brand,model,domain,url,time.time()))
                evidence=c.execute('SELECT COUNT(DISTINCT domain) FROM catalog_evidence WHERE brand=? AND model=? AND observed_at>?',
                                   (brand,model,time.time()-90*86400)).fetchone()[0]
                if evidence>=2:
                    existing=c.execute('SELECT 1 FROM vehicle_catalog WHERE brand=? AND model=? AND trim=?',(brand,model,'')).fetchone()
                    if not existing:
                        c.execute('INSERT OR IGNORE INTO vehicle_catalog(brand,model,trim,aliases_json,source,updated_at) VALUES(?,?,?,?,?,?)',
                                  (brand,model,'','[]','auto_verified_2_sources',time.time()))
                        promoted+=1
            c.commit()
    _discovery_status={'state':'completed' if not errors else 'partial','last_run':time.time(),
                       'checked':checked,'promoted':promoted,'error':'; '.join(errors[:3]) or None}
    return dict(_discovery_status)

def _discovery_worker(brands):
    global _discovery_status
    try:
        _discover_once(brands)
    except Exception as exc:
        _discovery_status={'state':'failed','last_run':time.time(),'checked':0,'promoted':0,'error':str(exc)[:250]}
    finally:
        _discovery_lock.release()

@app.post('/api/catalog/discover')
def discover_catalog(brand:str='',_=Depends(authorized)):
    if not _discovery_lock.acquire(blocking=False):
        raise HTTPException(409,'کشف خودروها در حال اجراست')
    selected=[brand.strip()] if brand.strip() else DISCOVERY_BRANDS
    _discovery_status.update(state='running',error=None)
    threading.Thread(target=_discovery_worker,args=(selected,),daemon=True).start()
    return {'state':'started','brands':selected[:3],'note':'در هر اجرا حداکثر سه برند برای کنترل هزینه بررسی می‌شود'}

@app.get('/api/catalog/discovery-status')
def discovery_status(_=Depends(authorized)):
    return dict(_discovery_status)

@app.get('/api/catalog/evidence')
def catalog_evidence(brand:str='',model:str='',_=Depends(authorized)):
    with discovery_db() as c:
        rows=c.execute('SELECT brand,model,domain,url,observed_at FROM catalog_evidence WHERE (?="" OR brand=?) AND (?="" OR model=?) ORDER BY observed_at DESC LIMIT 200',
                       (brand,brand,model,model)).fetchall()
    return {'items':[dict(r) for r in rows]}

def _auto_discovery_loop():
    # Three brands per day, rotating through the list; no user input required.
    # Delayed first pass lets the app start and keeps deployment health fast.
    time.sleep(60)
    with discovery_db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS catalog_sync_state(key TEXT PRIMARY KEY,value TEXT)')
        saved=c.execute("SELECT value FROM catalog_sync_state WHERE key='cursor'").fetchone()
        index=int(saved[0])%len(DISCOVERY_BRANDS) if saved else 0
    while True:
        if AVALAI_KEY and OPENAI_KEY and _discovery_lock.acquire(blocking=False):
            selected=[DISCOVERY_BRANDS[(index+j)%len(DISCOVERY_BRANDS)] for j in range(3)]
            _discovery_worker(selected)
            index=(index+3)%len(DISCOVERY_BRANDS)
            with discovery_db() as c:
                c.execute("INSERT OR REPLACE INTO catalog_sync_state VALUES('cursor',?)",(str(index),))
                c.commit()
        time.sleep(DISCOVERY_INTERVAL_HOURS*3600)

if DISCOVERY_ENABLED:
    threading.Thread(target=_auto_discovery_loop,daemon=True).start()

@app.post('/api/catalog/import')
def catalog_import(body:VehicleImport,_=Depends(authorized)):
    return {'imported':upsert_vehicles(body.items)}

@app.get('/api/catalog')
def catalog_list(q:str='',limit:int=Query(default=100,ge=1,le=500),offset:int=Query(default=0,ge=0),_=Depends(authorized)):
    with catalog_db() as c:
        rows=c.execute('SELECT id,brand,model,trim,aliases_json,source,updated_at FROM vehicle_catalog ORDER BY brand,model,trim LIMIT ? OFFSET ?',(limit,offset)).fetchall()
        total=c.execute('SELECT COUNT(*) FROM vehicle_catalog').fetchone()[0]
    entries=[dict(x) for x in rows]
    for entry in entries:entry['aliases']=json.loads(entry.pop('aliases_json'))
    if q:
        entries=[x for x in entries if norm_vehicle(q) in norm_vehicle(' '.join([x['brand'],x['model'],x['trim']]+x['aliases']))]
    return {'items':entries,'total':total}

@app.get('/api/catalog/suggest')
def catalog_suggest(brand:str='',model:str='',_=Depends(authorized)):
    with catalog_db() as c:
        rows=c.execute('SELECT brand,model,trim,aliases_json FROM vehicle_catalog LIMIT 20000').fetchall()
    b=norm_vehicle(brand);m=norm_vehicle(model)
    matching=[dict(x) for x in rows if (not b or b in norm_vehicle(x['brand'])) and (not m or m in norm_vehicle(x['model']))]
    return {'models':sorted(set(x['model'] for x in matching))[:80], 'trims':sorted(set(x['trim'] for x in matching if x['trim']))[:80]}

def dynamic_voice_match(transcript):
    text=norm_vehicle(transcript)
    with catalog_db() as c:
        rows=c.execute('SELECT brand,model,trim,aliases_json FROM vehicle_catalog LIMIT 20000').fetchall()
    candidates=[]
    for row in rows:
        names=[row['model']+' '+row['trim'] if row['trim'] else row['model'],row['brand']+' '+row['model']]+json.loads(row['aliases_json'])
        for alias in names:
            token=norm_vehicle(alias)
            if len(token)>=3 and re.search(r'(?<!\w)'+re.escape(token)+r'(?!\w)',text):
                candidates.append((len(token),dict(row)))
    return max(candidates,key=lambda x:x[0])[1] if candidates else None


def correct_spoken_vehicle_name(text):
    """Normalize high-confidence Persian speech-to-text variants."""
    return re.sub(r'(?<!\w)(?:فیتیلی|فیدیلیتی|فیدیلتی|فیدلیتى|فیدلیتی)(?!\w)', 'فیدلیتی', text, flags=re.IGNORECASE)


def parse_voice(text):
    t=re.sub(r'\s+',' ',text.translate(FA_DIGITS).replace('ي','ی').replace('ك','ک').replace('‌',' ')).strip()
    t=correct_spoken_vehicle_name(t)
    low=t.lower()
    is_new=bool(re.search(r'(?<!\w)(?:نو|صفر|صفر\s*کیلومتر|آکبند|اکبند|خشک)(?!\w)',low))
    aliases=[('چری','تیگو ۷ پرو مکس',[r'تیگو\s*(?:7|۷|هفت)\s*پرو\s*مکس',r'tiggo\s*7\s*pro\s*max']),('چری','تیگو ۷ پرو',[r'تیگو\s*(?:7|۷|هفت)\s*پرو',r'tiggo\s*7\s*pro']),('چری','تیگو ۷',[r'تیگو\s*(?:7|۷|هفت)',r'tiggo\s*[- ]?7',r'چری\s*تیگو\s*هفت']),('چری','تیگو ۸ پرو',[r'تیگو\s*(?:8|۸|هشت)\s*پرو',r'tiggo\s*8\s*pro']),('چری','تیگو ۸',[r'تیگو\s*(?:8|۸|هشت)',r'tiggo\s*[- ]?8']),('سیتروئن','C4',[r'(?<![a-z0-9])c\s*[- ]?4(?![a-z0-9])',r'سی\s*فور',r'سی\s*چهار',r'سیتروئن\s*سی\s*(?:فور|چهار|4)',r'citroen\s*c4']),('سیتروئن','C3',[r'(?<![a-z0-9])c\s*[- ]?3(?![a-z0-9])',r'سی\s*تری',r'سی\s*سه']),('بی ام و','X3',[r'(?<![a-z0-9])x\s*3(?![a-z0-9])',r'ایکس\s*(?:تری|سه|3)']),('هیوندای','سانتافه',[r'سانتافه',r'سانتافایه',r'santafe',r'santa\s*fe']),('هیوندای','توسان',[r'توسان',r'tucson']),('کیا','اسپورتیج',[r'اسپورتیج',r'sportage']),('تویوتا','کمری',[r'کمری',r'camry']),('پژو','۲۰۷',[r'(?<!\d)207(?!\d)',r'دویست\s*و\s*هفت',r'دو\s*صفر\s*هفت',r'دو\s*صفر\s*هفت',r'تو\s*اُ\s*سون']),('پژو','۲۰۶',[r'(?<!\d)206(?!\d)',r'دویست\s*و\s*شش',r'دو\s*صفر\s*شش']),('ایران خودرو','دنا پلاس',[r'دنا\s*پلاس']),('ایران خودرو','تارا',[r'تارا']),('سایپا','شاهین',[r'شاهین']),('کیا','سراتو',[r'سراتو']),('هیوندای','النترا',[r'النترا'])]
    # Common brand aliases, including speech-to-text variations in Persian/English.
    # Match longer/more specific models first, then fall back to the brand alone.
    aliases = [
        ('آئودی','A3L',[r'(?<![a-z0-9])a\s*3\s*l(?![a-z0-9])',r'ای\s*سه\s*ال',r'ای\s*تری\s*ال',r'آ\s*سه\s*ال']),
        ('آئودی','A3',[r'(?<![a-z0-9])a\s*3(?![a-z0-9l])',r'ای\s*سه(?!\s*ال)',r'ای\s*تری(?!\s*ال)']),
        ('آئودی','Q4 e-tron',[r'q\s*4\s*(?:e[ -]?tron)?',r'کیو\s*فور',r'کیو\s*چهار']),
        ('آئودی','Q5',[r'q\s*5',r'کیو\s*فایو',r'کیو\s*پنج']),
        ('آئودی','Q3',[r'q\s*3',r'کیو\s*تری',r'کیو\s*سه']),
        ('آئودی','A4',[r'(?<![a-z0-9])a\s*4(?![a-z0-9])',r'ای\s*فور',r'ای\s*چهار']),
        ('آئودی','A5',[r'(?<![a-z0-9])a\s*5(?![a-z0-9])',r'ای\s*فایو',r'ای\s*پنج']),
        ('آئودی','A6',[r'(?<![a-z0-9])a\s*6(?![a-z0-9])',r'ای\s*سیکس',r'ای\s*شش']),
    ] + aliases
    brand_aliases = [
        ('آئودی',[r'آ[یئ]ودی',r'ا[یئ]ودی',r'آودی',r'اودی',r'آئدی',r'آدی',r'\baudi\b',r'\baudie\b']),
        ('بی ام و',[r'بی\s*ام\s*و',r'\bbmw\b']),
        ('مرسدس بنز',[r'مرسدس',r'بنز',r'mercedes']),
        ('هیوندای',[r'هیوندای',r'hyundai']),
        ('تویوتا',[r'تویوتا',r'toyota']),
        ('کیا',[r'\bkia\b',r'کیا']),
        ('پژو',[r'پژو',r'peugeot']),
        ('چری',[r'چری',r'chery',r'تیگو',r'tiggo']),
        ('سیتروئن',[r'سیتروئن',r'citroen',r'citro[eë]n']),
        ('فولکس واگن',[r'فولکس',r'volkswagen',r'\bvw\b']),
        ('رنو',[r'رنو',r'renault']),
        ('نیسان',[r'نیسان',r'nissan']),
        ('هوندا',[r'هوندا',r'honda']),
        ('لکسوس',[r'لکسوس',r'lexus']),
    ]
    brand=model=None
    for b,m,patterns in aliases:
        if any(re.search(x,low) for x in patterns):brand=b;model=m;break

    # Expandable brand/model catalog; exact model names and families, not hard-coded one-off voice cases.
    # Prefer the longest matching model so e.g. «تیگو ۷ پرو مکس» is not reduced to «تیگو ۷».
    catalog = {
      'ایران خودرو':['پژو پارس','پارس سال','پارس تی یو فایو','پژو ۴۰۵','پژو ۲۰۰۸','رانا پلاس','رانا','سورن پلاس','سورن','سمند ال ایکس','سمند','دنا پلاس توربو','دنا پلاس','دنا','تارا','ری را','آریسان','هایما اس ۷','هایما اس ۵','هایما ۸ اس','هایما ۷ ایکس'],
      'سایپا':['شاهین پلاس','شاهین','اطلس','سهند','ساینا اس','ساینا','کوییک آر','کوییک اس','کوییک','پراید ۱۳۱','پراید ۱۱۱','پراید','تیبا ۲','تیبا'],
      'مدیران خودرو':['ام وی ام ایکس ۲۲ پرو','ام وی ام ایکس ۲۲','ام وی ام ایکس ۳۳','ام وی ام ایکس ۵۵ پرو','ام وی ام ایکس ۵۵','آریزو ۵ اسپرت','آریزو ۵','آریزو ۶ پرو','آریزو ۶','آریزو ۸','فونیکس اف ایکس','فونیکس تیگو ۷ پرو','فونیکس تیگو ۸ پرو مکس'],
      'چری':['تیگو ۹','تیگو ۸ پرو مکس','تیگو ۸ پرو','تیگو ۸','تیگو ۷ پرو مکس','تیگو ۷ پرو','تیگو ۷','تیگو ۵','آریزو ۸','آریزو ۶ پرو','آریزو ۶','آریزو ۵'],
      'کرمان موتور':['جک اس ۵','جک اس ۳','جک جی ۴','کی ام سی تی ۹','کی ام سی تی ۸','کی ام سی جی ۷','کی ام سی ایکس ۵','کی ام سی ای ۵','کی ام سی جی ۴'],
      'بهمن موتور':['فیدلیتی پرستیژ','فیدلیتی پرایم','فیدلیتی','دیگنیتی پرستیژ','دیگنیتی','ریسپکت','بستیون تی ۷۷','اینرودز'],
      'هیوندای':['سانتافه','توسان','النترا','سوناتا','آزرا','اکسنت','جنسیس','کونا','کرتا','آی ۲۰','آی ۳۰'],
      'کیا':['اسپورتیج','سراتو','اپتیما','سورنتو','ریو','پیکانتو','سلتوس','استونیک','کارنیوال','کی ۵'],
      'تویوتا':['کرولا کراس','کرولا','کمری','راو ۴','لندکروزر','پرادو','هایلوکس','یاریس','لوین','سی اچ آر'],
      'نیسان':['ایکس تریل','جوک','قشقایی','ماکسیما','تیانا','پاترول','سانی','آلتیما'],
      'رنو':['تندر ۹۰','ال ۹۰','ساندرو استپ وی','ساندرو','داستر','کپچر','کولیوس','تالیسمان','مگان','فلوئنس'],
      'مزدا':['مزدا ۳','مزدا ۲','سی ایکس ۵','سی ایکس ۳۰'],
      'هوندا':['سیویک','آکورد','سی آر وی','اچ آر وی','سیتی'],
      'لکسوس':['ان ایکس ۳۰۰','ان ایکس ۲۰۰','آر ایکس ۳۵۰','آر ایکس ۲۰۰','ای اس ۲۵۰','ال ایکس ۵۷۰'],
      'فولکس واگن':['تیگوان','پاسات','گلف','جتا','تی راک','آی دی ۴'],
      'مرسدس بنز':['سی ۲۰۰','سی ۱۸۰','ای ۲۰۰','ای ۳۰۰','اس ۵۰۰','جی ال سی','جی ال ای','جی ال ای ۴۵۰'],
      'بی ام و':['ایکس ۱','ایکس ۳','ایکس ۴','ایکس ۵','ایکس ۶','سری ۳','سری ۵','سری ۷'],
      'لاماری':['لاماری ایما','لاماری'],
      'فردا موتور':['اف ام سی تی ۵','اف ام سی اس ایکس ۵','اف ام سی اس ایکس ۶','فردا ۵۱۱'],
      'دیار خودرو':['بایک ایکس ۵۵','بایک بی جی ۴۰'],
      'میتسوبیشی':['اوتلندر','لنسر','ای اس ایکس','پاجرو'],
      'سوزوکی':['ویتارا','جیمنی','فرانکس','سیاز'],
      'پورشه':['ماکان','کاین','پانامرا','باکستر'],
      'ولوو':['ایکس سی ۹۰','ایکس سی ۶۰','اس ۹۰'],
      'جیلی':['امگرند','آزکارا','کولری'],
      'بی وای دی':['سانگ پلاس','چین پلاس','یوان پلاس','سیل'],
      'هونگچی':['اچ ۵','ای کیو ام ۵','اچ اس ۵'],
      'اکستریم':['وی ایکس','تی ایکس ال','ال ایکس'],
    }
    # Extended market catalog: domestic aliases and international model/trim families.
    catalog_extensions = {
      'چانگان':['سی اس ۳۵','سی اس ۳۵ پلاس','سی اس ۵۵ پلاس','سی اس ۷۵','یونی تی','یونی کی','یونی وی','آلسوین','ایدّو','دیپال اس ۰۷','دیپال ال ۰۷'],
      'هاوال':['اچ ۲','اچ ۶','اچ ۹','جولیون','بیگ داگ'],
      'جک':['اس ۲','اس ۳','اس ۵','اس ۷','جی ۴','جی ۵','جی ۷','تی ۸','تی ۹','جی اس ۴'],
      'کی ام سی':['ایگل','ای ۵','ایکس ۵','ایکس ۶','جی ۷','تی ۸','تی ۹','اس آر ۳','ای ۳۰ ایکس'],
      'فونیکس':['اف ایکس','اف ایکس پریمیوم','آریزو ۶ جی تی','آریزو ۶ پرو','آریزو ۸','تیگو ۷ پرو','تیگو ۷ پرو مکس','تیگو ۷ پرو ای پلاس','تیگو ۸ پرو','تیگو ۸ پرو مکس','تیگو ۸ پرو ای پلاس','اف ۹'],
      'ام وی ام':['ایکس ۲۲','ایکس ۲۲ پرو','ایکس ۳۳','ایکس ۳۳ کراس','ایکس ۵۵','ایکس ۵۵ پرو','ایکس ۷۷','آریزو ۵','آریزو ۵ اسپرت','۳۱۵','۵۳۰','۵۵۰'],
      'اکستریم':['ال ایکس','تی ایکس ال','وی ایکس','ای اس'],
      'لوکانو':['ال ۵','ال ۷','ال ۸','جی ۵','جی ۷','جی ۸'],
      'فیدلیتی':['پرایم','پرستیژ','الیت','ایکس ۳'],
      'دیگنیتی':['پرایم','پرستیژ'],
      'لاماری':['ایما','ایما هیبرید','اکو','نئو','فلو'],
      'بایک':['بی جی ۴۰','بی جی ۳۰','ایکس ۵۵','یو ۵','ایکس ۳۵'],
      'تیگارد':['ایکس ۳۵','ایکس ۳۵ پلاس'],
      'بی وای دی':['سانگ پلاس','چین پلاس','چین ال','یوان پلاس','دلفین','سیل','اتو ۳','تانگ','هان'],
      'جیلی':['امگرند ۷','امگرند ایکس ۷','کولری','آزکارا','مونجارو','اکس ۳ پرو','جیومتری سی'],
      'دانگ فنگ':['شاین مکس','شاین','اچ ۳۰ کراس','اس ۳۰','تی ۵','آئولوس'],
      'هونگچی':['اچ ۵','اچ ۹','ای اچ اس ۷','ای کیو ام ۵','اچ اس ۵'],
      'وویا':['فری','دریم','پشن'],
      'آواتار':['۱۱','۱۲','۰۷'],
      'اکس پنگ':['جی ۶','جی ۹','پی ۷'],
      'لیپ موتور':['تی ۰۳','سی ۱۰','سی ۱۶'],
      'بی ام و':['۱۱۸ آی','۱۲۰ آی','۱۲۵ آی','۲۱۸ آی','۲۲۰ آی','۲۲۸ آی','۲۳۰ آی','۳۱۶ آی','۳۱۸ آی','۳۲۰ آی','۳۲۵ آی','۳۲۸ آی','۳۳۰ آی','۳۳۵ آی','۳۴۰ آی','۴۲۰ آی','۴۲۸ آی','۴۳۰ آی','۴۴۰ آی','۵۲۰ آی','۵۲۳ آی','۵۲۵ آی','۵۲۸ آی','۵۳۰ آی','۵۳۵ آی','۵۴۰ آی','۵۵۰ آی','۷۳۰ آی','۷۳۵ آی','۷۴۰ آی','۷۴۵ آی','۷۵۰ آی','۷۶۰ آی','ایکس ۱','ایکس ۲','ایکس ۳','ایکس ۴','ایکس ۵','ایکس ۶','ایکس ۷','ایکس ام','زد ۴','ام ۲','ام ۳','ام ۴','ام ۵','ام ۶','ام ۸','آی ۳','آی ۴','آی ۵','آی ۷','آی ۸','آی ایکس','ایکس ۳ ام','ایکس ۵ ام','ایکس ۶ ام'],
      'مرسدس بنز':['ای ۲۰۰','ای ۲۳۰','ای ۲۴۰','ای ۲۵۰','ای ۳۰۰','ای ۳۵۰','ای ۴۰۰','ای ۵۰۰','سی ۱۸۰','سی ۲۰۰','سی ۲۳۰','سی ۲۵۰','سی ۳۰۰','سی ۳۵۰','اس ۳۵۰','اس ۴۰۰','اس ۴۵۰','اس ۵۰۰','اس ۵۵۰','اس ۵۸۰','اس ۶۰۰','سی ال ای ۲۰۰','سی ال ای ۲۵۰','سی ال اس ۳۵۰','سی ال اس ۵۰۰','جی ال ای','جی ال سی','جی ال اس','جی ال ای ۴۵۰','جی ال سی ۳۰۰','جی ال ای ۳۵۰','جی ال ای ۵۳','جی کلاس','جی ۶۳','جی ۵۰۰','ای کیو ای','ای کیو اس','ای کیو بی','ای کیو سی','ای ام جی جی تی','اس ال ۵۰۰','وی کلاس','ای کلاس','سی کلاس','اس کلاس'],
      'کیا':['سراتو','سراتو کوپه','اپتیما','کی ۵','کی ۳','کی ۸','کی ۹','اسپورتیج','سورنتو','موهاوی','سلتوس','سونت','استونیک','پیکانتو','ریو','کارنیوال','کادنزا','کوريس','نیرو','ای وی ۵','ای وی ۶','ای وی ۹'],
      'هیوندای':['سانتافه','سانتافه آی ایکس ۴۵','توسان','توسان آی ایکس ۳۵','کونا','کرتا','النترا','سوناتا','سوناتا هیبرید','آزرا','گرنجور','اکسنت','ورنا','جنسیس','جنسیس کوپه','ولستر','آی ۱۰','آی ۲۰','آی ۳۰','آی ۴۰','پالیسید','استاریا','یونیگ ۵','یونیک ۶','ونیو'],
      'جنسیس':['جی ۷۰','جی ۸۰','جی ۹۰','جی وی ۶۰','جی وی ۷۰','جی وی ۸۰'],
      'سانگ یانگ':['تیوولی','کوراندو','رکستون','اکتیون','کایرون','موسو','تورِس','تورِس ای وی ایکس'],
    }
    for ext_brand,ext_models in catalog_extensions.items():
        catalog.setdefault(ext_brand,[]).extend(ext_models)
    def norm_car(x):
        x=x.lower().translate(FA_DIGITS).replace('ي','ی').replace('ك','ک').replace('‌',' ')
        return re.sub(r'[^\w]+','',x)
    # Optional catalog file can be updated without editing Python parser logic.
    try:
        extra_path=Path(os.getenv('CAR_CATALOG_PATH','/app/data/car_catalog.json'))
        if extra_path.is_file():
            extra=json.loads(extra_path.read_text(encoding='utf-8'))
            if isinstance(extra,dict):
                for name,items in extra.items():
                    if isinstance(name,str) and isinstance(items,list):
                        catalog.setdefault(name,[]).extend(x for x in items if isinstance(x,str) and 2<=len(x)<=80)
    except (OSError,ValueError,TypeError) as exc:
        logging.warning('Car catalog skipped: %s',exc)
    if not model:
        normalized=norm_car(low)
        hits=[(len(norm_car(m)),brand_name,m) for brand_name,models in catalog.items() for m in models
              if len(norm_car(m))>=4 and norm_car(m) in normalized]
        if hits:
            _,brand,model=max(hits)
    # Generic recognition: where the brand is known but model is not in the catalog,
    # retain a candidate only if it follows the brand explicitly. Ask for confirmation.
    candidate_model=None
    if not model:
        brand_terms={'هیوندای':['هیوندای','hyundai'],'کیا':['کیا','kia'],'تویوتا':['تویوتا','toyota'],
          'نیسان':['نیسان','nissan'],'رنو':['رنو','renault'],'چری':['چری','chery'],
          'پژو':['پژو','peugeot'],'مرسدس بنز':['مرسدس','بنز','mercedes'],
          'بی ام و':['بی ام و','bmw'],'آئودی':['آئودی','اودی','audi']}
        for brand_name,terms in brand_terms.items():
            for term in terms:
                match=re.search(re.escape(term)+r'\s+([\wآ-ی-]+(?:\s+[\wآ-ی-]+){0,2})',low)
                if match:
                    words=match.group(1).split()
                    stop={'مدل','سال','کارکرد','کار','هزار','کیلومتر','سفید','مشکی','قرمز','نو','صفر','بدون','رنگ'}
                    model_words=[]
                    for word in words:
                        if word in stop or re.fullmatch(r'(?:13|14|19|20)\d{2}',word):break
                        model_words.append(word)
                    if model_words:
                        brand=brand_name
                        candidate_model=' '.join(model_words)
                        break
            if candidate_model:break
    if candidate_model and not model: model=candidate_model

    # A brand-only utterance is valid: ask for the model rather than losing the brand.
    if not brand:
        for b,patterns in brand_aliases:
            if any(re.search(pattern,low,re.IGNORECASE) for pattern in patterns):
                brand=b
                break
    # Audi model identifiers must not be inferred from an isolated digit or year.
    if brand=='آئودی' and not model:
        for code in ('A3L','A3','A4','A5','A6','Q3','Q4','Q5','Q7','Q8'):
            if re.search(r'(?<![a-z0-9])'+re.escape(code.lower())+r'(?![a-z0-9])',low):
                model=code
                break
    # Only a year explicitly introduced as «مدل / سال / ساخت» is a confirmed model year.
    # This deliberately prevents a mileage number from becoming a model year.
    year=None
    year_phrase=re.search(r'(?<!\w)(?:مدل|سال(?:\s*ساخت)?|ساخت)\s*(?:سال\s*)?((?:\d{2,4}|[آ-ی\s]{3,65}))',low)
    if year_phrase:
        raw=year_phrase.group(1).strip()
        numeric=re.match(r'\d{2,4}(?!\d)',raw)
        if numeric:
            value=int(numeric.group())
            if 70<=value<=99:value+=1300
            elif 0<=value<=10:value+=1400
            if 1350<=value<=1450 or 1950<=value<=2035:year=value
        else:
            words=raw.split()
            for length in range(min(8,len(words)),1,-1):
                value=spoken_number(words[:length])
                if value is not None and (1350<=value<=1450 or 1950<=value<=2035):
                    year=value;break
    # A standalone four-digit calendar year is valid when not attached to mileage.
    # Examples: «نیسان پاترول 2025» -> 2025; «پژو ۲۰۶ ۲۰۰۰ تا کارکرد» -> no year.
    if year is None:
        for candidate in re.finditer(r'(?<![\w\d])(1[34]\d{2}|19\d{2}|20\d{2})(?!\d)',low):
            value=int(candidate.group(1))
            if not (1350<=value<=1450 or 1950<=value<=2035):
                continue
            after=low[candidate.end():candidate.end()+30]
            before=low[max(0,candidate.start()-20):candidate.start()]
            if re.match(r'\\s*(?:هزار\\s*)?(?:تا\\s*)?(?:کارکرد|کار\\s*کرده|کار|کیلومتر|رفته)',after):
                continue
            if re.search(r'(?:کارکرد|کیلومتر|رفته)\\s*$',before):
                continue
            year=value
            break
    mileage=None
    # Parse mileage only when the speech actually includes a mileage context.
    km_context=r'(?:کیلومتر|کیلومتر\s*کارکرد|تا\s*کار(?:کرد)?|کارکرد|کار\s*کرده|رفته)'
    m=re.search(r'(?<!\d)(\d{1,7})\s*هزار\s*(?:تا\s*)?'+km_context,low)
    if m:mileage=int(m.group(1))*1000
    if mileage is None:
        m=re.search(r'(?<!\d)(\d{1,7})\s*'+km_context,low)
        if m:mileage=int(m.group(1))
    if mileage is None:
        m=re.search(r'(?<![\w])(?:یک\s+)?هزار\s*(?:تا\s*)?'+km_context,low)
        if m:mileage=1000
    if mileage is None:
        m=re.search(r'((?:یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|بیست|سی|چهل|پنجاه|شصت|هفتاد|هشتاد|نود|صد|دویست|سیصد|چهارصد|پانصد|و|\s)+)\s+هزار\s*(?:تا\s*)?'+km_context,low)
        if m:
            n=spoken_number(m.group(1).split())
            if n is not None and 1<=n<=999:mileage=n*1000
    # Explicit mileage wins if a 4-digit number is followed by «تا کارکرد».
    # A year must be introduced by «مدل/سال/ساخت» and must not borrow mileage digits.
    # Keep an explicit calendar year, even when mileage is mentioned next.
    # A number in a mileage phrase alone must not become the model year.
    # Explicit contextual mileage (e.g. «کارکرد ۵۰ هزار») overrides ambiguous numeric patterns.
    parsed_km=mileage_from_description(t)
    if parsed_km is not None:mileage=parsed_km
    if is_new and mileage is None:mileage=0
    condition=None
    if any(x in low for x in ['بدون رنگ','بی رنگ','بیرنگ','فابریک']):condition='بدون رنگ'
    elif 'گلگیر' in low or 'گل گیر' in low:
        if 'تعویض' in low:condition='یک گلگیر تعویض‌شده'
        elif 'رنگ' in low:condition='یک گلگیر رنگ‌شده'
        elif 'ضربه' in low:condition='یک گلگیر ضربه‌خورده بدون رنگ'
    elif 'درب' in low and 'رنگ' in low:condition='یک درب رنگ‌شده'
    elif 'رنگ' in low:condition='چند قطعه رنگ‌شده'
    # Extract explicitly mentioned body parts and paint color. Unsaid fields stay unknown.
    part_patterns = [
        ('کاپوت',r'کاپوت'),('صندوق عقب',r'صندوق(?:\s*عقب)?'),
        ('درب جلو راننده',r'درب\s*جلو\s*راننده'),('درب عقب راننده',r'درب\s*عقب\s*راننده'),
        ('درب جلو شاگرد',r'درب\s*جلو\s*شاگرد'),('درب عقب شاگرد',r'درب\s*عقب\s*شاگرد'),
        ('گلگیر جلو راننده',r'گل\s*گیر\s*جلو\s*راننده'),('گلگیر عقب راننده',r'گل\s*گیر\s*عقب\s*راننده'),
        ('گلگیر جلو شاگرد',r'گل\s*گیر\s*جلو\s*شاگرد'),('گلگیر عقب شاگرد',r'گل\s*گیر\s*عقب\s*شاگرد'),
        ('سقف',r'سقف'),
    ]
    body_parts={}
    for name,pattern in part_patterns:
        for match in re.finditer(pattern,low):
            vicinity=low[max(0,match.start()-24):min(len(low),match.end()+30)]
            # Avoid treating «بدون رنگ» as a painted part.
            if re.search(r'تعویض|عوض\s*شده',vicinity):status='تعویض‌شده'
            elif re.search(r'ضربه|تو\s*رفتگی',vicinity):status='ضربه بدون رنگ' if re.search(r'بدون\s*رنگ',vicinity) else 'ضربه بدون رنگ'
            elif re.search(r'رنگ\s*شده|رنگ\s*داره|رنگ\s*خورده',vicinity) and not re.search(r'بدون\s*رنگ|بی\s*رنگ',vicinity):status='رنگ‌شده'
            else:continue
            body_parts[name]=status
    # Common short expressions: «گلگیر جلو چپ رنگ».
    side_aliases={'چپ':'راننده','راست':'شاگرد'}
    for side,canonical in side_aliases.items():
        for pos in ('جلو','عقب'):
            m=re.search(r'گل\s*گیر\s*'+pos+r'\s*'+side+r'\s*(?:هم\s*)?(رنگ|تعویض|ضربه)',low)
            if m:body_parts['گلگیر '+pos+' '+canonical]={'رنگ':'رنگ‌شده','تعویض':'تعویض‌شده','ضربه':'ضربه بدون رنگ'}[m.group(1)]
    # Car exterior color may be spoken without the word «رنگ».
    # Longer color names first; normalize colloquial spellings and STT variations.
    color_aliases=[
        ('آلبالویی',[r'آلبالوی(?:ی)?',r'البالوی(?:ی)?',r'آلبالو(?:یی|ئی|ی)?',r'البالو(?:یی|ئی|ی)?',r'آل\s*بالو(?:یی|ی)?',r'البالویی']),
        ('نوک مدادی',[r'نوک\s*مدادی']),('نقره‌ای',[r'نقره\s*ای',r'نقره‌ای']),
        ('سفید',[r'سفید']),('مشکی',[r'مشکی',r'سیاه']),('قرمز',[r'قرمز']),
        ('آبی',[r'آبی']),('خاکستری',[r'خاکستری']),('بژ',[r'بژ']),
        ('قهوه‌ای',[r'قهوه\s*ای']),('سبز',[r'سبز']),('طلایی',[r'طلایی']),('زرد',[r'زرد'])]
    car_color=None
    for canonical,patterns in color_aliases:
        if any(re.search(r'(?<![\w])(?:'+pat+r')(?![\w])',low) for pat in patterns):
            car_color=canonical;break
    transmission='اتوماتیک' if re.search(r'اتومات|اتومَت|automatic',low) else ('دستی' if re.search(r'دنده\s*ای|دنده\s*دستی|manual',low) else None)
    trim=None
    if re.search(r'3300|سه هزار و سیصد',low):trim='۳۳۰۰ سی‌سی'
    elif re.search(r'2400|دو هزار و چهارصد',low):trim='۲۴۰۰ سی‌سی'
    elif 'mpi' in low:trim='MPI'
    elif 'gdi' in low:trim='GDI'
    missing=[]
    if not model:missing.append('مدل خودرو')
    if not year:missing.append('سال تولید')
    if mileage is None:missing.append('کارکرد')
    if not condition:missing.append('وضعیت بدنه')
    if model=='۲۰۶':
        m=re.search(r'(?:تیپ|type|tip)\s*([۲۳۵۶2356]|دو|سه|پنج|شش)',low)
        if m:
            num={'دو':'۲','سه':'۳','پنج':'۵','شش':'۶','2':'۲','3':'۳','5':'۵','6':'۶'}.get(m.group(1),m.group(1))
            trim='تیپ '+num
    elif model=='۲۰۷':
        if re.search(r'پانوراما|پانورامیک',low):trim='پانوراما'
        elif re.search(r'مولتی\s*کالر|مولتی\s*کالر',low):trim='مولتی کالر'
    needs_trim=bool((model=='۲۰۶' and not trim) or (model=='سانتافه' and year and 2013<=year<=2018 and not trim))
    if re.search(r'(?<!\w)فیدلیتی(?!\w)',low):
        brand='بهمن موتور'
        model='فیدلیتی'
        if re.search(r'پرستیژ',low): trim='پرستیژ'
        elif re.search(r'پرایم',low): trim='پرایم'
        elif re.search(r'الیت',low): trim='الیت'
    dynamic=dynamic_voice_match(t)
    if dynamic and not model:
        brand=dynamic['brand'];model=dynamic['model']
        if dynamic['trim'] and not trim:trim=dynamic['trim']
        needs_trim=False
    # Unspecified variants are questions, not guessed values.
    questions=[]
    if not model:questions.append('مدل دقیق خودرو چیست؟')
    if not year:questions.append('سال ساخت خودرو چند است؟')
    if mileage is None and not is_new:questions.append('کارکرد خودرو چند کیلومتر است؟')
    if not trim and (re.search(r'سری\s*[1-8]|series\s*[1-8]|کلاس\s*[ces]|class\s*[ces]',low,re.I) or model in ('۲۰۶','سانتافه')):
        questions.append('تیپ یا نوع موتور خودرو چیست؟')
    if not condition:questions.append('وضعیت بدنه خودرو چگونه است؟')
    # v22: low-risk phrase NLP. Fuzzy matches are only shown as suggestions.
    identified=identify_vehicle(t)
    suggestion=None
    if not model and identified:
        if identified['type']=='alias':
            brand=identified['brand']; model=identified['model']
        else:
            suggestion={'brand':identified['brand'],'model':identified['model'],'confidence':identified['confidence']}
    if model and not trim:
        trim=variant_from_text(t,model)
    generation=generation_from_text(t)
    needs_trim=bool(needs_trim or (model=='فیدلیتی' and not trim))
    # Ask only the most actionable missing field; color/body remain optional.
    questions=[]
    if not model:
        questions.append('مدل خودرو چیست؟')
    elif needs_trim:
        questions.append('فیدلیتی پرایم، پرستیژ یا الیت است؟' if model=='فیدلیتی' else 'تیپ یا موتور خودرو چیست؟')
    elif not year:
        questions.append('سال ساخت خودرو چند است؟')
    elif mileage is None and not is_new:
        questions.append('کارکرد خودرو چند کیلومتر است؟')
    return {'questions':questions,'brand':brand,'model':model,'year':year,'mileage':mileage,'condition':condition,'trim':trim,'needs_trim':needs_trim,'missing':missing,'transcript':t,'body_parts':body_parts,'color':car_color,'transmission':transmission,'is_new':is_new,'generation':generation,'model_suggestion':suggestion,'recognition_alias':identified['alias'] if identified and identified['type']=='alias' else None}

class VoiceInput(BaseModel):
    text:str=Field(min_length=2,max_length=300)
@app.post('/api/parse-voice')
def voice_parse(body:VoiceInput,_=Depends(authorized)):
    return parse_voice(body.text)

def enforce_rate(client_key='default'):
    now=time.time()
    with _rate_lock:
        history=[t for t in _recent_calls_by_client.get(client_key,[]) if now-t<3600]
        if len(history)>=MAX_SEARCHES_PER_HOUR: raise RuntimeError('سقف استعلام ساعتی پر شده است؛ از تاریخچه استفاده کنید.')
        if now-_last_search_by_client.get(client_key,0)<SEARCH_COOLDOWN: raise RuntimeError('برای کاهش مصرف API، چند ثانیه بعد دوباره تلاش کنید یا از تاریخچه استفاده کنید.')
        history.append(now)
        _recent_calls_by_client[client_key]=history
        _recent_calls[:]=[t for t in _recent_calls if now-t<3600]
        _recent_calls.append(now)
        _last_search[0]=now
        _last_search_by_client[client_key]=now
        if len(_last_search_by_client)>1000:
            for key in list(_last_search_by_client):
                if now-_last_search_by_client[key]>3600:
                    _last_search_by_client.pop(key,None)
                    _recent_calls_by_client.pop(key,None)

@app.get('/api/health')
def health(): return {'status':'ok','app':'davoodi-car','version':'28.0.0-name-only-market'}

@app.get('/api/browser-check')
def browser_check(_=Depends(authorized)):
    """On-demand Chromium JS smoke test on Liara; no third-party requests."""
    from connectors.browser import BrowserSession
    session=BrowserSession()
    try:
        session._start()
        session.page.set_content('<div id="probe"></div><script>document.getElementById("probe").textContent="js-ok"</script>')
        session.page.wait_for_function('document.getElementById("probe").textContent==="js-ok"',timeout=2500)
        return {'status':'ok','browser':'chromium','javascript':'ok'}
    except Exception as exc:
        logging.warning('Browser smoke test failed: %s',exc)
        raise HTTPException(503,detail='Chromium در Liara قابل اجرا نیست: '+str(exc).splitlines()[0][:160])
    finally:
        session.close()

@app.get('/api/readiness')
def readiness():
    try:
        with db() as c:
            c.execute('SELECT 1').fetchone()
        database='ok'
    except Exception:
        logging.exception('Database readiness failure')
        database='error'
    status='ready' if database=='ok' else 'unavailable'
    return {'status':status,'database':database,'source_count':len(SOURCE_CONNECTORS),
            'fallback_configured':bool(AVALAI_KEY),
            'market_fetch_mode':os.getenv('MARKET_FETCH_MODE','playwright').lower(),
            'browser_check_endpoint':'/api/browser-check',
            'browser_connectors':['bama.ir','hamrah-mechanic.com','khodro45.com','divar.ir'],
            'version':'28.0.0-name-only-market'}


# Public vehicle reference photography from Wikimedia Commons (not an advert photo).
# Images are separate from market-price sources and never treated as price evidence.
PHOTO_MODELS = {
 'آئودی':'Audi', 'اودی':'Audi', 'سانتافه':'Hyundai Santa Fe', 'هیوندای':'Hyundai',
 'پژو':'Peugeot', 'تویوتا':'Toyota', 'کمری':'Toyota Camry', 'دنا':'IKCO Dena',
 'سیتروئن':'Citroen', 'سی فور':'Citroen C4', 'بنز':'Mercedes-Benz',
 'بی ام و':'BMW', 'کیا':'Kia', 'سراتو':'Kia Cerato', 'اسپورتیج':'Kia Sportage',
 'تیگو':'Chery Tiggo', 'ام وی ام':'Chery', 'فونیکس':'Fownix',
}
def photo_search_text(q):
    q=re.sub(r'[۰-۹٠-٩]',lambda m: str('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'.index(m.group())%10),q)
    for fa,en in sorted(PHOTO_MODELS.items(),key=lambda x:-len(x[0])):
        q=q.replace(fa,en)
    q=re.sub(r'(?i)\b(?:بدون رنگ|کارکرد|کیلومتر|قیمت|چنده|چقدر|رنگ شده|مدل)\b',' ',q)
    q=re.sub(r'\b(?:1[34]\d{2}|20\d{2}|\d{5,7})\b',' ',q)
    return ' '.join(q.split())[:75]

def wiki_api(host, params, timeout=6):
    from urllib.parse import urlencode
    req=Request('https://'+host+'/w/api.php?'+urlencode(dict(params,format='json',formatversion=2)),headers={'User-Agent':'DavoodiCar/1.5 (car media lookup; contact: webmaster@davoodicar.ir)','Accept':'application/json'})
    with urlopen(req,timeout=timeout) as r:return json.load(r)

def wiki_page_photo(term):
    # Independent fallback: Wikipedia article lead photo (not Commons file search).
    from urllib.parse import quote
    for host in ('en.wikipedia.org',):
        for title in (term,term+' (car)',term.split(' ')[0] if ' ' in term else term):
            try:
                data=wiki_api(host,{'action':'query','titles':title,'redirects':1,'prop':'pageimages','pithumbsize':850},5)
                for page in data.get('query',{}).get('pages',[]):
                    url=page.get('thumbnail',{}).get('source','')
                    if url.startswith('https://') and not url.lower().split('?')[0].endswith('.svg'):
                        return {'image_url':url,'image_page':'https://en.wikipedia.org/wiki/'+quote(page['title'].replace(' ','_')),'photo_label':'تصویر نمونه از ویکی‌پدیا؛ تطابق سال و تیپ باید بررسی شود'}
            except Exception as exc:logging.info('Wikipedia photo fallback failed: %s',exc)
    return None

def wikidata_brand_logo(brand):
    # Manufacturer logo is Wikidata property P154, not the article photo.
    from urllib.parse import quote
    try:
        pages=wiki_api('en.wikipedia.org',{'action':'query','titles':brand,'redirects':1,'prop':'pageprops','ppprop':'wikibase_item'},5).get('query',{}).get('pages',[])
        qid=next((p.get('pageprops',{}).get('wikibase_item') for p in pages if p.get('pageprops',{}).get('wikibase_item')),None)
        if not qid:return None
        data=wiki_api('www.wikidata.org',{'action':'wbgetentities','ids':qid,'props':'claims'},5)
        claims=data.get('entities',{}).get(qid,{}).get('claims',{}).get('P154',[])
        for claim in claims:
            filename=claim.get('mainsnak',{}).get('datavalue',{}).get('value')
            if not isinstance(filename,str):continue
            return {'brand':brand,'logo_url':'https://commons.wikimedia.org/wiki/Special:Redirect/file/'+quote(filename,safe=''),'source_url':'https://www.wikidata.org/wiki/'+qid,'note':'لوگوی رسمی ثبت‌شده در ویکی‌داده'}
    except Exception as exc:logging.info('Wikidata logo fallback failed: %s',exc)
    return None


CAR_IMAGE_ALIASES = {
    'سانتافه': ['hyundai santa fe', 'santa fe'],
    'هیوندای سانتافه': ['hyundai santa fe', 'santa fe'],
    '۲۰۷': ['peugeot 207'],
    '207': ['peugeot 207'],
    '۲۰۶': ['peugeot 206'],
    '206': ['peugeot 206'],
    'دنا پلاس': ['ikco dena plus', 'dena plus'],
    'دنا': ['ikco dena'],
    'کمری': ['toyota camry'],
    'آئودی a3': ['audi a3'],
    'audi a3': ['audi a3'],
}

def _image_terms_for_car(query: str):
    q = normalize_text(query).lower() if 'normalize_text' in globals() else str(query).lower()
    terms = []
    for key, aliases in CAR_IMAGE_ALIASES.items():
        if key.lower() in q:
            terms.extend(aliases)
    if not terms:
        # Use a conservative Latin-ish fallback only if query already contains model-like tokens.
        cleaned = re.sub(r'[^a-zA-Z0-9\s\-]', ' ', str(query)).strip().lower()
        if cleaned:
            terms.append(cleaned)
    return list(dict.fromkeys(terms))

def _car_image_matches(title: str, query: str):
    title_l = (title or '').lower().replace('_',' ')
    aliases = _image_terms_for_car(query)
    if not aliases:
        return False
    return any(alias in title_l for alias in aliases)


# Private curated photo bank. Photos are stored on persistent Liara volume.
# No automated photo search is used: a missing photo remains missing.
from fastapi import UploadFile, File, Form
from fastapi.responses import Response
from urllib.parse import quote
CAR_PHOTO_DIR = Path(os.getenv('CAR_PHOTO_DIR','/app/data/car_photos'))
CAR_PHOTO_INDEX = CAR_PHOTO_DIR / 'index.json'
CAR_MODELS = {
    'santafe': ['سانتافه','santa fe','santafe'],
    'peugeot-206': ['۲۰۶','206','دویست و شش'],
    'peugeot-207': ['۲۰۷','207','دویست و هفت'],
    'dena-plus': ['دنا پلاس','dena plus'],
    'dena': ['دنا','dena'],
    'camry': ['کمری','camry'],
    'audi-a3': ['a3l','a3','آئودی ای سه'],
    'cerato': ['سراتو','cerato'],
    'sportage': ['اسپورتیج','sportage'],
    'tucson': ['توسان','tucson'],
    'pride': ['پراید','pride'],
    'tara': ['تارا','tara'],
    'shahin': ['شاهین','shahin'],
    'pars': ['پژو پارس','peugeot pars'],
    'samand': ['سمند','samand'],
}
def car_photo_key(q):
    q=str(q).lower().replace('ي','ی').replace('ك','ک')
    for key,aliases in CAR_MODELS.items():
        if any(alias in q for alias in aliases):return key
    return None
def load_photo_index():
    try:return json.loads(CAR_PHOTO_INDEX.read_text('utf-8'))
    except (FileNotFoundError,ValueError):return {}
def local_car_photo(query):
    key=car_photo_key(query)
    if not key:return {'image_url':None,'note':'مدل خودرو در بانک تصویر داخلی تعریف نشده است'}
    entry=load_photo_index().get(key)
    if not entry:return {'image_url':None,'note':'عکس تأییدشده این مدل هنوز در بانک داخلی ثبت نشده است'}
    filename=entry.get('filename','')
    if filename not in (key+'.jpg',key+'.png',key+'.webp') or not (CAR_PHOTO_DIR/filename).is_file():
        return {'image_url':None,'note':'فایل عکس ثبت‌شده در فضای ذخیره‌سازی موجود نیست'}
    return {'image_url':'/api/car-photo-file/'+key,'image_page':None,
            'photo_label':'عکس مرجع تأییدشده؛ ممکن است سال و تیپ متفاوت باشد',
            'source':'internal','model_key':key}
@app.get('/api/car-photo-file/{key}')
def car_photo_file(key:str, _:bool=Depends(authorized)):
    if key not in CAR_MODELS:raise HTTPException(404,'مدل یافت نشد')
    entry=load_photo_index().get(key) or {}
    filename=entry.get('filename','')
    if filename not in (key+'.jpg',key+'.png',key+'.webp'):
        raise HTTPException(404,'تصویر ثبت نشده است')
    path=CAR_PHOTO_DIR/filename
    if not path.is_file():raise HTTPException(404,'فایل تصویر موجود نیست')
    return FileResponse(path)
@app.get('/api/car-photo-bank')
def car_photo_bank(_:bool=Depends(authorized)):
    entries=load_photo_index()
    return {'models':[{'key':key,'aliases':aliases,'available':key in entries} for key,aliases in CAR_MODELS.items()]}
@app.post('/api/car-photo-bank/{key}')
async def upload_car_photo(key:str, photo:UploadFile=File(...), _:bool=Depends(authorized)):
    if key not in CAR_MODELS:raise HTTPException(404,'مدل ناشناخته')
    raw=await photo.read(4_000_001)
    if len(raw)>4_000_000:raise HTTPException(413,'حداکثر حجم تصویر ۴ مگابایت است')
    ext=None
    if raw[:3]==b'\xff\xd8\xff':ext='jpg'
    elif raw[:8]==b'\x89PNG\r\n\x1a\n':ext='png'
    elif raw[:4]==b'RIFF' and raw[8:12]==b'WEBP':ext='webp'
    if not ext:raise HTTPException(400,'فقط تصویر JPG، PNG یا WebP پذیرفته می‌شود')
    CAR_PHOTO_DIR.mkdir(parents=True,exist_ok=True)
    filename=key+'.'+ext
    tmp=CAR_PHOTO_DIR/(filename+'.tmp')
    tmp.write_bytes(raw)
    tmp.replace(CAR_PHOTO_DIR/filename)
    index=load_photo_index()
    index[key]={'filename':filename,'uploaded_at':datetime.now(timezone.utc).isoformat()}
    tmp_index=CAR_PHOTO_DIR/'index.json.tmp'
    tmp_index.write_text(json.dumps(index,ensure_ascii=False),encoding='utf-8')
    tmp_index.replace(CAR_PHOTO_INDEX)
    return {'ok':True,'model_key':key,'image_url':'/api/car-photo-file/'+key}

@app.get('/api/car-image')
def car_image(query: str=Query(min_length=2,max_length=180), _:bool=Depends(authorized)):
    return local_car_photo(query)

# Brand marks are looked up independently from vehicle photographs.
# Only a recognized manufacturer is used; never guess a different brand logo.
BRAND_LOGOS = {
    'آئودی':'Audi', 'اودی':'Audi', 'audi':'Audi',
    'هیوندای':'Hyundai', 'سانتافه':'Hyundai', 'hyundai':'Hyundai',
    'پژو':'Peugeot', 'peugeot':'Peugeot',
    'تویوتا':'Toyota', 'کمری':'Toyota', 'toyota':'Toyota',
    'سیتروئن':'Citroen', 'citroen':'Citroen',
    'بنز':'Mercedes-Benz', 'مرسدس':'Mercedes-Benz', 'mercedes':'Mercedes-Benz',
    'بی ام و':'BMW', 'بی‌ام‌و':'BMW', 'bmw':'BMW',
    'کیا':'Kia', 'سراتو':'Kia', 'اسپورتیج':'Kia', 'kia':'Kia',
    'دنا':'Iran Khodro', 'پارس':'Iran Khodro', 'سمند':'Iran Khodro',
    'ایران خودرو':'Iran Khodro', 'تیگو':'Chery', 'ام وی ام':'Chery',
    'فونیکس':'Fownix', 'چری':'Chery', 'chery':'Chery',
    'رنو':'Renault', 'renault':'Renault', 'فولکس':'Volkswagen',
    'volkswagen':'Volkswagen', 'نیسان':'Nissan', 'nissan':'Nissan',
    'مزدا':'Mazda', 'mazda':'Mazda', 'هوندا':'Honda', 'honda':'Honda',
    'لکسوس':'Lexus', 'lexus':'Lexus', 'پورشه':'Porsche', 'porsche':'Porsche',
    'ولوو':'Volvo', 'volvo':'Volvo', 'فورد':'Ford', 'ford':'Ford',
    'سوزوکی':'Suzuki', 'suzuki':'Suzuki', 'میتسوبیشی':'Mitsubishi',
    'mitsubishi':'Mitsubishi', 'جک':'JAC Motors', 'jac':'JAC Motors',
    'هایما':'Haima', 'haima':'Haima', 'بهمن':'Bahman',
}

@app.get('/api/brand-logo')
def brand_logo(query: str=Query(min_length=2,max_length=180), _:bool=Depends(authorized)):
    from urllib.parse import urlencode, quote
    normalized=query.lower().replace('ي','ی').replace('ك','ک').replace('آ','ا')
    brand=None
    for key,english in sorted(BRAND_LOGOS.items(),key=lambda kv:-len(kv[0])):
        k=key.lower().replace('ي','ی').replace('ك','ک').replace('آ','ا')
        if re.search(r'(?<![a-z])'+re.escape(k)+r'(?![a-z])',normalized):
            brand=english;break
    if not brand:
        return {'brand':None,'logo_url':None,'note':'برند خودرو شناسایی نشد'}
    params=urlencode({'action':'query','generator':'search',
       'gsrsearch':brand+' automobile manufacturer logo', 'gsrnamespace':6,
       'gsrlimit':15,'prop':'imageinfo','iiprop':'url','iiurlwidth':220,'format':'json'})
    try:
        req=Request('https://commons.wikimedia.org/w/api.php?'+params,
           headers={'User-Agent':'DavoodiCar/1.0 (car brand mark lookup)'})
        with urlopen(req,timeout=8) as resp: data=json.load(resp)
        pages=sorted(data.get('query',{}).get('pages',{}).values(),key=lambda x:x.get('index',99))
        keywords=[x.lower() for x in brand.split()]
        for page in pages:
            title=page.get('title','').lower()
            if not all(k in title for k in keywords):continue
            if not any(x in title for x in ('logo','emblem','badge')):continue
            if any(x in title for x in ('old','historical','former','concept','dealership','flag','racing')):continue
            info=(page.get('imageinfo') or [{}])[0]
            url=info.get('thumburl') or info.get('url')
            if not url or not url.startswith('https://upload.wikimedia.org/'):continue
            return {'brand':brand,'logo_url':url,
               'source_url':'https://commons.wikimedia.org/wiki/'+quote(page['title'].replace(' ','_'),safe='/:_'),
               'note':'نشان تجاری از ویکی‌مدیا؛ در صورت نبود تطابق معتبر نمایش داده نمی‌شود'}
    except Exception as exc:
        logging.info('Brand logo lookup unavailable: %s',exc)
    return wikidata_brand_logo(brand) or {'brand':brand,'logo_url':None,'note':'لوگو در Commons و Wikidata یافت نشد یا سرور به این سرویس‌ها دسترسی ندارد.'}

_login_lock=threading.Lock()
_login_failures={}
_login_blocked_until={}

def _client_login_key(request:Request):
    # Trust only the connection address; Uvicorn proxy trust must be configured
    # at the infrastructure layer rather than accepting user-supplied XFF.
    return request.client.host if request.client else 'unknown'

def enforce_login_rate(client_key):
    now=time.monotonic()
    with _login_lock:
        blocked=_login_blocked_until.get(client_key,0.0)
        if now<blocked:
            raise HTTPException(429,'تلاش‌های ورود بیش از حد است؛ چند دقیقه بعد دوباره تلاش کنید',headers={'Retry-After':str(max(1,int(blocked-now)))})
        # Bounded memory; discard entries whose block and failures have expired.
        if len(_login_failures)>1024:
            for key in list(_login_failures):
                if key!=client_key and all(now-x>900 for x in _login_failures[key]):
                    _login_failures.pop(key,None)
                    _login_blocked_until.pop(key,None)

def login_failed(client_key):
    now=time.monotonic()
    with _login_lock:
        attempts=[x for x in _login_failures.get(client_key,[]) if now-x<900]
        attempts.append(now)
        if len(attempts)>=5:
            _login_blocked_until[client_key]=now+300
            attempts=[]
        _login_failures[client_key]=attempts

def login_succeeded(client_key):
    with _login_lock:
        _login_failures.pop(client_key,None)
        _login_blocked_until.pop(client_key,None)

@app.post('/api/login')
def login(body:Login,request:Request):
    client_key=_client_login_key(request)
    enforce_login_rate(client_key)
    if not hmac.compare_digest(body.password.encode(),PASSWORD.encode()):
        login_failed(client_key)
        raise HTTPException(401,'رمز عبور یا دسترسی نامعتبر است')
    login_succeeded(client_key)
    return {'token':make_token(),'expires_in':28800}

def post_json(url,payload,headers,service='سرویس خارجی',timeout=32):
    request=Request(url,data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers={'Content-Type':'application/json',**headers},method='POST')
    for attempt in range(2):
        try:
            with urlopen(request,timeout=timeout) as response: return json.load(response)
        except HTTPError as e:
            detail=e.read(500).decode(errors='replace')
            logging.warning('%s HTTP %s: %s',service,e.code,detail)
            if e.code==429:
                retry=e.headers.get('Retry-After','')
                try: wait=min(max(float(retry),0),4)
                except ValueError: wait=2.0
                if attempt==0 and wait<=4:
                    time.sleep(wait+random.uniform(.1,.5)); continue
                raise RuntimeError(service+' موقتاً محدود شده است (429). چند دقیقه بعد دوباره تلاش کنید؛ نتایج ذخیره‌شده همچنان قابل استفاده‌اند.')
            if e.code in (401,403): raise RuntimeError(service+' دسترسی را رد کرد ('+str(e.code)+'). اعتبار کلید و مجوز حساب را بررسی کنید.')
            raise RuntimeError(service+' خطای HTTP '+str(e.code)+' برگرداند')
        except (URLError,TimeoutError) as e:
            logging.error('API connectivity: %s',str(e))
            raise RuntimeError('ارتباط سرور با '+service+' برقرار نشد')

# ---------- Market data architecture v16 ----------
# Source connectors -> normalized listings -> evidence filter -> statistical price engine.
# LLM is used only for explanation, never to invent or calculate market prices.
SOURCE_CONNECTORS = [
    {'name':'دیوار','domain':'divar.ir','env':'DIVAR_CONNECTOR_URL'},
    {'name':'باما','domain':'bama.ir','env':'BAMA_CONNECTOR_URL'},
    {'name':'همراه مکانیک','domain':'hamrah-mechanic.com','env':'HAMRAH_CONNECTOR_URL'},
    {'name':'خودرو۴۵','domain':'khodro45.com','env':'KHODRO45_CONNECTOR_URL'},
    {'name':'کارنامه','domain':'karnameh.com','env':'KARNAMEH_CONNECTOR_URL'},
    {'name':'شیپور','domain':'sheypoor.com','env':'SHEYPOOR_CONNECTOR_URL'},
]

def _norm_text(value):
    value=str(value or '').translate(FA_DIGITS).lower().replace('ي','ی').replace('ك','ک').replace('‌',' ')
    return re.sub(r'\s+',' ',value).strip()

def _price_from_text(text):
    """Only return an unambiguous vehicle asking price, never a fee or installment."""
    return explicit_vehicle_price(text)

def _mileage_from_text(text):
    return mileage_from_description(text)

def _year_from_text(text):
    t=_norm_text(text)
    vals=[]
    for m in re.finditer(r'(?<!\d)(13\d{2}|14\d{2}|19\d{2}|20\d{2})(?!\d)',t):
        y=int(m.group(1))
        if 1350<=y<=1450 or 1950<=y<=2035: vals.append(y)
    return vals[0] if vals else None

def _kind_from_url_title(url,title):
    """Conservative page classifier: editorial/search/category pages are never price evidence."""
    from urllib.parse import urlparse
    parsed=urlparse(url); path=(parsed.path or '').lower(); txt=_norm_text(title)
    editorial_path=r'/(mag|blog|news|car-reviews|review|reviews|article|articles|specs|wiki|guide|academy|learn)(/|$)'
    editorial_text=(r'مشخصات\s*فنی|بررسی\s*(?:خودرو|کامل)|راهنمای\s*(?:خرید|فروش)|اخبار|مقایسه\s*خودرو|'
                    r'مزایا\s*و\s*معایب|نقد\s*و\s*بررسی|معرفی\s*خودرو|کاتالوگ|دانلود\s*کاتالوگ|'
                    r'قیمت\s*کارخانه\s*و\s*بازار|شرایط\s*فروش|ثبت\s*نام|مشخصات\s*موتور')
    if re.search(editorial_path,path) or re.search(editorial_text,txt): return 'article'
    # Explicit individual-ad URL patterns supported by current public sites.
    if 'bama.ir' in url and '/car/detail-' in path: return 'listing'
    if 'hamrah-mechanic.com' in url and re.search(r'/cars-for-sale/[^/]+/[^/]+/\d+/?$',path): return 'listing'
    if 'divar.ir' in url and re.fullmatch(r'/v/(?:[^/]+/)?[\w-]{4,}/?',path): return 'listing'
    if 'sheypoor.com' in url and re.search(r'/(s/|listing/|v/)[^/]+',path): return 'listing'
    if re.search(r'/(used-cars/|listing/|ads/|vehicles/)',path): return 'listing'
    # Search/category pages are discovery only, never evidence.
    if re.search(r'/(s|search|cars-for-sale|car|vehicles|price)/?$',path): return 'category'
    if 'divar.ir' in url and re.search(r'/s/',path): return 'category'
    return 'unknown'

def _vehicle_tokens(vehicle):
    fields=[vehicle.get('brand'),vehicle.get('model'),vehicle.get('trim')]
    toks=[]
    for field in fields:
        for x in re.findall(r'[\wآ-ی]+',_norm_text(field)):
            if len(x)>1 and x not in ('مدل','خودرو'): toks.append(x)
    return list(dict.fromkeys(toks))

def _relevance(vehicle,title,content):
    """Require the requested model; never reject a valid listing for omitting maker."""
    text=_norm_text((title or '')+' '+(content or ''))
    model=_norm_text(vehicle.get('model'))
    brand=_norm_text(vehicle.get('brand'))
    trim=_norm_text(vehicle.get('trim'))
    if model:
        tokens=[x for x in model.split() if len(x)>1 or x.isdigit()]
        matched=sum(bool(re.search(r'(?<!\w)'+re.escape(x)+r'(?!\w)',text)) for x in tokens)
        coverage=matched/max(1,len(tokens))
        if coverage<.60:
            recognized=identify_vehicle(text)
            if recognized and _norm_text(recognized.get('model'))==model:
                coverage=1
        score=75*coverage
    else:
        score=25 if brand and brand in text else 0
    if brand and brand in text:score+=10
    req_year=vehicle.get('year'); seen_year=_year_from_text(text)
    year_ok=True
    if req_year and seen_year:
        from market_intelligence import compatible_year
        relation=compatible_year(req_year,seen_year)
        if relation is False:year_ok=False
        if relation is True:score+=10
    if trim and trim in text:score+=5
    return round(min(100,score),1),year_ok

def _structured_number(value, *, kind):
    """Parse connector JSON values without mistaking a string value for evidence.

    Price must carry an explicit amount; currency conversion is only performed
    for values explicitly labeled as rial. Unknown formats return None.
    """
    if value is None or isinstance(value, bool): return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    if not isinstance(value, str): return None
    raw=_norm_text(value).replace('٬','').replace(',','').strip()
    if kind=='price':
        if re.search(r'میلیارد|میلیون|تومان|ریال',raw):
            return _price_from_text(raw)
        if re.fullmatch(r'\d{7,13}',raw): return int(raw)
        return None
    if kind=='mileage':
        m=re.fullmatch(r'(\d{1,7})\s*(هزار|کیلومتر|km)?',raw)
        if m:
            return int(m.group(1))*(1000 if m.group(2)=='هزار' else 1)
        return None
    if kind=='year':
        if re.fullmatch(r'1[34]\d{2}|19\d{2}|20\d{2}',raw): return int(raw)
    return None


def _normalize_result(source,row,vehicle):
    from urllib.parse import urlparse
    url=str(row.get('url') or row.get('link') or '')
    title=str(row.get('title') or '')[:220]
    content=str(row.get('content') or row.get('snippet') or row.get('description') or '')[:2200]
    kind=str(row.get('kind') or _kind_from_url_title(url,title))
    price=_structured_number(row.get('price'),kind='price')
    if price is None: price=_price_from_text(title+' '+content)
    # A source cannot turn an editorial URL into a listing by labeling it as one.
    if _kind_from_url_title(url,title)=='article': kind='article'
    if kind=='unknown' and source['domain'] in ('khodro45.com','karnameh.com') and price is not None:
        # These sources may expose reference-price pages without a stable listing URL pattern.
        # Editorial/category pages were already excluded by the classifier above.
        kind='market_price'
    mileage=_structured_number(row.get('mileage'),kind='mileage')
    if mileage is None: mileage=_mileage_from_text(title+' '+content)
    year=_structured_number(row.get('year'),kind='year')
    if year is None: year=_year_from_text(title+' '+content)
    score,year_ok=_relevance(vehicle,title,content)
    rejection=None
    if row.get('price_conflict'):rejection='قیمت کارت آگهی و صفحه جزئیات ناسازگار است'
    elif row.get('detail_mismatch'):rejection='مشخصات صفحه جزئیات با کارت آگهی متفاوت است'
    elif kind not in ('listing','market_price'): rejection='این نتیجه آگهی فروش یا مرجع قیمت معتبر نیست'
    elif score<45: rejection='مدل/تیپ با خودروی درخواستی تطابق کافی ندارد'
    elif not year_ok: rejection='سال آگهی با سال درخواستی متفاوت است'
    elif price is None: rejection='قیمت صریح قابل استخراج نیست'
    host=(urlparse(url).hostname or '').lower().removeprefix('www.')
    if not (host == source['domain'] or host.endswith('.' + source['domain'])):
        rejection='لینک منبع خارج از دامنه رسمی سایت است'
    is_new=new_status(title+' '+content, mileage, row.get('is_new'))
    return {'source':source['name'],'domain':host or source['domain'],'url':url,'title':title,'content':content,
            'kind':kind,'price':int(price) if price else None,'mileage':mileage,'year':year,
            'relevance':score,'is_new':is_new,'accepted':rejection is None,'rejection_reason':rejection,
            'trim':row.get('trim') or variant_from_text(title+' '+content, vehicle.get('model')),'city':row.get('city'),
            'condition':row.get('condition') or row.get('body_condition'),'color':row.get('color'),'published_at':row.get('published_at') or row.get('posted_at'), 'detail_error':row.get('detail_error'),
            'price_conflict':bool(row.get('price_conflict')), 'detail_mismatch':bool(row.get('detail_mismatch'))}

def _direct_connector(source,vehicle):
    """Optional first-class connector. Expected JSON: {items:[{url,title,price,mileage,year,kind}]}.
    This lets an official/licensed API or internal MCP bridge replace web search without code changes.
    """
    endpoint=os.getenv(source['env'],'').strip()
    if not endpoint:return None
    payload={'brand':vehicle.get('brand'),'model':vehicle.get('model'),'trim':vehicle.get('trim'),
             'year':vehicle.get('year'),'mileage':vehicle.get('mileage'),'condition':vehicle.get('condition'),
             'query':vehicle.get('query')}
    data=post_json(endpoint,payload,{},source['name']+' connector')
    rows=data.get('items',[]) if isinstance(data,dict) else []
    return rows if isinstance(rows,list) else []

def _builtin_connector(source,vehicle):
    """Bundled public-web connector. Uses only ordinary public pages, no login/CAPTCHA bypass.
    Returns None when no native connector exists for that source.
    """
    try:
        return run_builtin_connector(source['domain'],vehicle,limit=35)
    except RuntimeError:
        raise
    except Exception as exc:
        logging.exception('builtin connector failure for %s',source['domain'])
        raise RuntimeError(source['name']+' کانکتور داخلی خطا داد: '+str(exc)[:120])

def _search_terms(vehicle):
    parts=[vehicle.get('brand'),vehicle.get('model'),vehicle.get('trim'),vehicle.get('city')]
    year=vehicle.get('year')
    if isinstance(year,int):
        parts.append(year)
        # Iranian marketplaces may index the same model-year in Gregorian or Solar-Hijri form.
        if 1900<=year<=2100: parts.append(year-621)
        elif 1300<=year<=1500: parts.append(year+621)
    terms=' '.join(str(x) for x in parts if x and str(x).strip())
    return terms or str(vehicle.get('query') or '').strip()

def _fallback_query(vehicle,source):
    """Build one source-specific query instead of mixing several domains in one broad query."""
    terms=_search_terms(vehicle)
    domain=source['domain']
    if domain in ('khodro45.com','karnameh.com'):
        intent='قیمت روز خودرو تومان'
    else:
        intent='آگهی فروش خودرو قیمت تومان'
    if vehicle.get('mileage') == 0 or str(vehicle.get('condition') or '').strip() in ('صفر','نو','صفر کیلومتر'):
        intent+=' صفر کیلومتر'
    return f'site:{domain} {terms} {intent}'.strip()

def _search_fallback_domain(vehicle,source):
    """Discover URLs with the search provider, verify facts on the source page.

    Search snippets are NOT evidence: they can be stale, omit mileage, or
    contain a price from another ad. Accept only directly fetched source pages.
    """
    from urllib.parse import urlparse
    from connectors.browser import source_session
    from connectors.common import fetch_html, matches_model
    from connectors.extract import detail_fields
    if not AVALAI_KEY:
        raise RuntimeError('جست‌وجوی تکمیلی فعال نیست: AVALAI_API_KEY تنظیم نشده است')
    q=_fallback_query(vehicle,source)
    # New key keeps previously cached, unverified snippets out of pricing.
    key='market-v27-verified:'+hashlib.sha256(q.casefold().encode()).hexdigest()
    hit=domain_saved(key,DOMAIN_CACHE_TTL)
    if hit:return hit.get('results',[])
    data=post_json('https://api.avalai.ir/v1/search/serper-search',{'query':q,'max_results':10,'hl':'fa'},
                   {'Authorization':'Bearer '+AVALAI_KEY},source['name']+' search fallback',timeout=18)
    rows=(data.get('results') or data.get('organic') or data.get('organic_results') or
          (data.get('data') or {}).get('results') or []) if isinstance(data,dict) else []
    if not isinstance(rows,list):rows=[]
    cap=max(1,min(10,int(os.getenv('MAX_FALLBACK_DETAIL_PAGES','5'))))
    checked=[];errors=[];urls=set()
    with source_session():
        for row in rows:
            if len(urls)>=cap:break
            if not isinstance(row,dict):continue
            url=str(row.get('url') or row.get('link') or '')
            parsed=urlparse(url)
            host=(parsed.hostname or '').lower().removeprefix('www.')
            if parsed.scheme!='https' or not (host==source['domain'] or host.endswith('.'+source['domain'])):
                continue
            kind=_kind_from_url_title(url,str(row.get('title') or ''))
            if kind=='article' or kind=='category' or url in urls:continue
            urls.add(url)
            try:
                details=detail_fields(fetch_html(url,timeout=7))
                title=details.get('title') or ''
                content=details.get('content') or ''
                if not matches_model(vehicle.get('brand'),vehicle.get('model'),title+' '+content):
                    continue
                if details.get('price') is None:
                    continue
                checked.append({'url':url,'title':title,'content':content,
                    'price':details['price'],'year':details.get('year'),
                    'mileage':details.get('mileage'),'published_at':details.get('published_at'),
                    'kind':kind if kind=='listing' else 'market_price' if source['domain'] in ('khodro45.com','karnameh.com') else 'unknown'})
            except (RuntimeError,ValueError,LookupError) as exc:
                errors.append(str(exc)[:120])
    if urls and not checked and len(errors)==len(urls):
        raise RuntimeError('هیچ صفحه‌ای از نتایج جست‌وجو قابل خواندن نبود: '+'؛ '.join(errors[:2]))
    if checked:domain_persist(key,{'results':checked,'query':q})
    return checked

def _weighted_stats(items,target_mileage=None):
    """v22: shared, evidence-aware, explainable price summary."""
    return price_summary(items, target_mileage)

def _explain_market(vehicle,new_stats,used_stats,diagnostics):
    # Deterministic summary is always available; LLM only improves wording.
    total=diagnostics['found']; accepted=diagnostics['accepted']
    base=f'{total} نتیجه خام بررسی شد و {accepted} شاهد قیمت‌دار و مرتبط پذیرفته شد.'
    limited=[]
    for label,stats in [('صفر',new_stats),('کارکرده',used_stats)]:
        if stats.get('limited_evidence'):
            limited.append(f"برای {label} فقط {stats.get('sample_count',0)} شاهد واقعی پیدا شد؛ دامنه مشاهده‌شده {stats.get('price_min',0):,} تا {stats.get('price_max',0):,} تومان است و برآورد آماری صادر نمی‌شود.")
    if limited: base+=' '+' '.join(limited)
    if used_stats.get('price_average'):
        base+=f" قیمت میانه بازار کارکرده {used_stats.get('price_median'):,} تومان است."
    if new_stats.get('price_average'):
        base+=f" قیمت میانه بازار صفر {new_stats.get('price_median'):,} تومان است."
    if not OPENAI_KEY:return base
    try:
        payload={'vehicle':vehicle,'new':new_stats,'used':used_stats,'diagnostics':diagnostics}
        sys=('فقط یک جمع‌بندی کوتاه فارسی برای کارشناس نمایشگاه بنویس. همه اعداد از JSON آمده‌اند؛ عدد جدید نساز. '
             'اگر نمونه کمتر از ۳ است آن را فقط «شواهد محدود» بنام و قیمت قطعی یا میانگین بازار اعلام نکن.')
        r=post_json('https://api.openai.com/v1/chat/completions',{'model':OPENAI_MODEL,'temperature':0.1,
             'messages':[{'role':'system','content':sys},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]},
             {'Authorization':'Bearer '+OPENAI_KEY},'OpenAI explanation',timeout=12)
        return str(r['choices'][0]['message']['content']).strip()[:1000]
    except Exception:
        return base

def research_market(vehicle):
    from urllib.parse import urlparse
    statuses=[]; normalized=[]; seen=set(); fallback_sources=[]
    # 1) Independent public/official connectors in parallel. Waiting for each
    # site sequentially could exceed the 105-second API deadline.
    from concurrent.futures import ThreadPoolExecutor

    def fetch_primary(source):
        try:
            rows = _direct_connector(source, vehicle)
            mode = 'external'
            if rows is None:
                rows = _builtin_connector(source, vehicle)
                mode = 'builtin_playwright' if os.getenv('MARKET_FETCH_MODE','playwright').lower() == 'playwright' else 'builtin_public'
            return rows, mode, None
        except RuntimeError as exc:
            return None, 'builtin_or_external', str(exc)[:120]
        except Exception as exc:
            logging.exception('Source connector failure: %s', source['domain'])
            return None, 'builtin_or_external', 'خطای غیرمنتظره در کانکتور'

    progress_report('بررسی مستقیم منابع',0,len(SOURCE_CONNECTORS))
    with ThreadPoolExecutor(max_workers=min(3,len(SOURCE_CONNECTORS))) as executor:
        tasks={source['domain']:executor.submit(fetch_primary,source) for source in SOURCE_CONNECTORS}
        for source in SOURCE_CONNECTORS:
            rows,mode,error=tasks[source['domain']].result()
            progress_report('بررسی مستقیم منابع',len(statuses)+1,len(SOURCE_CONNECTORS),source['name'])
            if error:
                statuses.append({'name':source['name'],'domain':source['domain'],'status':'connector_error',
                                 'count':0,'raw_count':0,'accepted_count':0,'mode':mode,'detail':error})
                fallback_sources.append(source)
                continue
            if rows is None:
                fallback_sources.append(source)
                continue
            raw_count=len(rows[:50]);added=0
            for row in rows[:50]:
                if not isinstance(row,dict):continue
                item=_normalize_result(source,row,vehicle)
                if not item['url'] or item['url'] in seen:continue
                seen.add(item['url']);normalized.append(item);added+=1
            accepted_count=sum(1 for x in normalized if x['source']==source['name'] and x['accepted'])
            statuses.append({'name':source['name'],'domain':source['domain'],
                             'status':'connector' if accepted_count else ('no_valid_evidence' if raw_count else 'no_results'),
                             'count':added,'raw_count':raw_count,'accepted_count':accepted_count,
                             'mode':mode})
            if accepted_count==0:fallback_sources.append(source)

    # 2) At most one focused fallback query per site, with a bounded worker
    # pool. Do not claim 'no results' when the search key is not configured.
    fallback_errors=[]; searched_domains=set();dedup=[]
    for source in fallback_sources:
        if source['domain'] not in searched_domains:
            searched_domains.add(source['domain']);dedup.append(source)
    candidates=dedup[:MAX_DOMAIN_REQUESTS]
    progress_report('جست‌وجوی تکمیلی',0,len(candidates))
    if AVALAI_KEY and candidates:
        # Enforce sequential requests when a nonzero per-request delay has been
        # explicitly configured by the operator.
        workers=1 if SEARCH_REQUEST_DELAY>0 else min(3,len(candidates))
        def fetch_fallback(index,source):
            if SEARCH_REQUEST_DELAY>0 and index:time.sleep(SEARCH_REQUEST_DELAY)
            return _search_fallback_domain(vehicle,source)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            tasks={source['domain']:executor.submit(fetch_fallback,i,source) for i,source in enumerate(candidates)}
            for source in candidates:
                progress_report('جست‌وجوی تکمیلی',candidates.index(source)+1,len(candidates),source['name'])
                try:
                    rows=tasks[source['domain']].result()
                    raw_count=len(rows);added=0;accepted_now=0
                    for row in rows:
                        if not isinstance(row,dict):continue
                        url=str(row.get('url') or row.get('link') or '')
                        try:host=(urlparse(url).hostname or '').lower().removeprefix('www.')
                        except ValueError:continue
                        if not (host==source['domain'] or host.endswith('.'+source['domain'])):continue
                        item=_normalize_result(source,row,vehicle)
                        if not item['url'] or item['url'] in seen:continue
                        seen.add(item['url']);normalized.append(item);added+=1
                        if item['accepted']:accepted_now+=1
                    statuses.append({'name':source['name'],'domain':source['domain'],
                                     'status':'searched' if added else 'no_results','count':added,'raw_count':raw_count,
                                     'accepted_count':accepted_now,'mode':'focused_search_fallback'})
                except RuntimeError as exc:
                    msg=str(exc);fallback_errors.append(source['name']+': '+msg)
                    statuses.append({'name':source['name'],'domain':source['domain'],
                                     'status':'rate_limited' if '429' in msg or 'محدود' in msg else 'error',
                                     'count':0,'raw_count':0,'accepted_count':0,'mode':'focused_search_fallback',
                                     'detail':msg[:120]})
                except Exception:
                    logging.exception('Source fallback failure: %s',source['domain'])
                    fallback_errors.append(source['name']+': خطای اتصال')
                    statuses.append({'name':source['name'],'domain':source['domain'],'status':'error',
                                     'count':0,'raw_count':0,'accepted_count':0,'mode':'focused_search_fallback',
                                     'detail':'خطای غیرمنتظره اتصال'})
    else:
        for source in candidates:
            statuses.append({'name':source['name'],'domain':source['domain'],'status':'not_configured',
                             'count':0,'raw_count':0,'accepted_count':0,'mode':'focused_search_fallback',
                             'detail':'جست‌وجوی تکمیلی غیرفعال: AVALAI_API_KEY تنظیم نشده است'})
    for source in dedup[MAX_DOMAIN_REQUESTS:]:
        statuses.append({'name':source['name'],'domain':source['domain'],'status':'not_checked',
                         'count':0,'raw_count':0,'accepted_count':0,'mode':'fallback_budget'})

    # Merge connector + fallback attempts into one readable status row per source.
    merged_status={}
    # A failed source must never be marked as "connected" simply because an
    # earlier listing page returned HTTP 200 with no usable advertisements.
    rank={'evidence':10,'rate_limited':9,'connector_error':9,'error':9,
          'searched':8,'no_valid_evidence':7,'no_results':6,'connector':5,
          'not_configured':3,'not_checked':2}
    for st in statuses:
        d=merged_status.setdefault(st['domain'],{'name':st['name'],'domain':st['domain'],'status':st['status'],
            'count':0,'raw_count':0,'accepted_count':0,'modes':[]})
        d['count']+=int(st.get('count') or 0); d['raw_count']+=int(st.get('raw_count') or 0)
        d['accepted_count']+=int(st.get('accepted_count') or 0)
        if st.get('mode') and st['mode'] not in d['modes']:d['modes'].append(st['mode'])
        if rank.get(st['status'],0)>rank.get(d['status'],0):d['status']=st['status']
        if st.get('detail') and not (st['status']=='not_configured' and d.get('detail')):d['detail']=st['detail']
    statuses=list(merged_status.values())
    for st in statuses:
        if st.get('accepted_count',0)>0:st['status']='evidence'

    # Re-assess source type, requested fields, freshness, and de-duplicate evidence.
    progress_report('اعتبارسنجی شواهد',1,1)
    assess_and_dedupe(normalized,vehicle,max_age_days=max(1,int(os.getenv('MAX_LISTING_AGE_DAYS','60'))))
    # Per-domain counts now reflect final accepted evidence, not only the raw parser output.
    for st in statuses:
        items=[x for x in normalized if x['domain']==st['domain']]
        st['accepted_count']=sum(x['accepted'] for x in items)
        st['rejected_count']=sum(not x['accepted'] for x in items)
        st['detail_errors']=sum(bool(x.get('detail_error')) for x in items)
        st['top_rejection_reasons']=[
            {'reason':reason,'count':count} for reason,count in sorted(
                ((reason,sum(x.get('rejection_reason')==reason for x in items)) for reason in
                 set(x.get('rejection_reason') for x in items if x.get('rejection_reason'))),
                key=lambda pair:-pair[1])[:3]]
        if st['accepted_count']:st['status']='evidence'
        elif st['status'] in ('connector','searched','no_results') and items:
            st['status']='no_valid_evidence'
    accepted=[x for x in normalized if x['accepted']]
    broad_query=name_only_search(vehicle)
    # Never pool asking prices from different model years, trims, or zero/used
    # cars when the user entered only a model name.
    overview=model_overview(vehicle,accepted) if broad_query else None
    new_items=[x for x in accepted if x['is_new']]
    used_items=[x for x in accepted if not x['is_new']]
    new_stats=_weighted_stats(new_items,0)
    used_stats=_weighted_stats(used_items,vehicle.get('mileage'))
    if broad_query:
        for stats in (new_stats,used_stats):
            stats.update({field:None for field in (
                'price_average','price_median','price_min','price_max',
                'suggested_min','suggested_max')})
            stats['histogram']=[]
            stats['limited_evidence']=True
            stats['pricing_note']='سال‌ها و تیپ‌ها جداگانه نمایش داده می‌شوند؛ میانگین کلی قابل استناد نیست.'
    # Do not remove old model-years as outliers of newer model-years.
    dropped_outliers=0 if broad_query else new_stats.get('outliers_removed',0)+used_stats.get('outliers_removed',0)
    if dropped_outliers:
        retained=set(new_stats.get('used_source_urls',[])+used_stats.get('used_source_urls',[]))
        for item in accepted:
            if item['url'] not in retained:
                item['accepted']=False
                item['rejection_reason']='قیمت پرت؛ خارج از دامنه داده‌های قابل استناد'
        accepted=[x for x in normalized if x['accepted']]
        for st in statuses:
            st['accepted_count']=sum(x['accepted'] for x in normalized if x['domain']==st['domain'])
            if st['accepted_count']:st['status']='evidence'
    diagnostics={'found':len(normalized),'accepted':len(accepted),'rejected':len(normalized)-len(accepted),
                 'reasons':{},'used_samples':used_stats.get('sample_count',0),'new_samples':new_stats.get('sample_count',0),
                 'articles_removed':0,'low_relevance_removed':0,'no_price_removed':0,
                 'duplicates_removed':0,'stale_removed':0,'outliers_removed':new_stats.get('outliers_removed',0)+used_stats.get('outliers_removed',0)}
    for x in normalized:
        if x['rejection_reason']:
            diagnostics['reasons'][x['rejection_reason']]=diagnostics['reasons'].get(x['rejection_reason'],0)+1
            if x['kind'] not in ('listing','market_price'): diagnostics['articles_removed']+=1
            elif 'تطابق' in x['rejection_reason']: diagnostics['low_relevance_removed']+=1
            elif 'قیمت صریح' in x['rejection_reason']: diagnostics['no_price_removed']+=1
            if 'تکراری' in x['rejection_reason']:diagnostics['duplicates_removed']+=1
            if 'قدیمی' in x['rejection_reason']:diagnostics['stale_removed']+=1
    warnings=[]
    inaccessible=[s['name'] for s in statuses if s.get('status') in ('connector_error','rate_limited','error')]
    if inaccessible:warnings.append('دسترسی یا استخراج در منابع زیر ناموفق بود؛ این موضوع به معنای نبود آگهی نیست: '+ '، '.join(inaccessible[:4]))
    if not AVALAI_KEY:
        warnings.append('جست‌وجوی پشتیبان فعال نیست: AVALAI_API_KEY در تنظیمات سرور وجود ندارد. پوشش آگهی‌ها ممکن است ناقص باشد.')
    if fallback_errors:warnings.append('برخی جست‌وجوهای منبع کامل نشدند: '+' | '.join(fallback_errors[:3]))
    if len(accepted)<3:
        if accepted:warnings.append('شواهد واقعی بازار پیدا شد، اما کمتر از ۳ نمونه است؛ فقط قیمت‌های مشاهده‌شده نمایش داده می‌شوند و میانگین بازار صادر نمی‌شود.')
        else:
            if diagnostics['found']:
                warnings.append('آگهی‌های اولیه دریافت شد، اما همگی در بررسی مشخصات/قیمت رد شدند؛ جزئیات ردشدن را در گزارش منابع ببینید.')
            else:
                warnings.append('هیچ شاهد قیمت‌دار دریافت نشد. وضعیت هر سایت و خطاهای دسترسی را بررسی کنید؛ این وضعیت به معنی نبود خودرو در بازار نیست.')
    summary=_explain_market(vehicle,new_stats,used_stats,diagnostics)
    verified=set((new_stats.get('used_source_urls') or [])+(used_stats.get('used_source_urls') or []))
    # Do not expose obvious editorial/irrelevant pages as "source cards" in the UI.
    displayable=[x for x in normalized if x['accepted']]
    sources=[{'title':x['title'],'url':x['url'],'category':x['source'],'kind':x['kind'],'domain':x['domain'],
              'price':x['price'],'mileage':x['mileage'],'year':x['year'],'relevance':x['relevance'],
              'accepted':x['accepted'],'rejection_reason':x['rejection_reason'],
              'quality_score':x.get('quality_score',0),'evidence_tier':x.get('evidence_tier'),
              'published_at':x.get('published_at'),'city':x.get('city'),'trim':x.get('trim')} for x in displayable]
    return {'summary':summary,'new':new_stats,'used':used_stats,'currency':'تومان','sources':sources,'image_url':None,
            'warnings':warnings,'site_status':statuses,'verified_source_urls':list(verified),'diagnostics':diagnostics,
            'vehicle':{k:vehicle.get(k) for k in ('brand','model','trim','year','mileage','city')},
            'model_overview':overview, 'engine':'v28-name-only-market',
            'pricing_method':'آگهی‌های واقعی گروه‌بندی‌شده بر اساس سال، تیپ و وضعیت خودرو' }

def resolve_search_vehicle(body: Search):
    """Resolve free-text manual searches before contacting paid/external sources.

    Explicit structured fields take priority. Fuzzy-only NLP guesses are not
    silently confirmed; users receive an actionable validation response.
    """
    raw = re.sub(r'\s+', ' ', body.query).strip()
    spoken = parse_voice(raw)
    brand = (body.brand or '').strip() or spoken.get('brand')
    model = (body.model or '').strip() or spoken.get('model')
    # The model must be explicit or confidently recognized; otherwise the query
    # is too ambiguous to price without inventing relevance.
    if not model:
        suggestion = spoken.get('model_suggestion')
        if suggestion:
            hint = f"آیا منظورتان {suggestion.get('brand')} {suggestion.get('model')} است؟ نام مدل را اصلاح و تأیید کنید."
        else:
            hint = 'مدل خودرو مشخص نیست. برای مثال «هیوندای سانتافه مدل ۲۰۲۵ صفر کیلومتر» را وارد کنید.'
        raise HTTPException(status_code=422, detail=hint)
    year = body.year if body.year is not None else spoken.get('year')
    mileage = body.mileage if body.mileage is not None else spoken.get('mileage')
    if mileage is None and spoken.get('is_new'):
        mileage = 0
    trim = (body.trim or '').strip() or spoken.get('trim') or None
    # Missing trim is fine for model-only queries; show separate trim groups.
    condition = (body.condition or '').strip() or spoken.get('condition') or None
    transmission = (body.transmission or '').strip() or spoken.get('transmission') or None
    color = (body.color or '').strip() or spoken.get('color') or None
    city = (body.city or '').strip() or None
    return {
        'query': raw, 'brand': brand, 'model': model, 'year': year,
        'mileage': mileage, 'condition': condition, 'transmission': transmission,
        'color': color, 'trim': trim, 'city': city,
    }


def _has_price_evidence(value):
    if not isinstance(value,dict):return False
    return bool((value.get('diagnostics') or {}).get('accepted',0) or
        (value.get('used') or {}).get('sample_count',0) or
        (value.get('new') or {}).get('sample_count',0))


def _effective_cache_ttl(value):
    # Do not keep "zero data" results for 15 minutes when connectivity recovers.
    return CACHE_TTL if _has_price_evidence(value) else EMPTY_RESULT_CACHE_TTL


@app.post('/api/search')
async def search(body:Search, request:Request, _=Depends(authorized)):
    vehicle=resolve_search_vehicle(body)
    query=vehicle['query']
    # Price search context is structured and deterministic. Every market-relevant
    # field participates in the cache key, so different years/trim/mileage cannot
    # incorrectly share a cached quote.
    key='v28:'+json.dumps({k:vehicle.get(k) for k in ('brand','model','year','mileage','condition','transmission','color','trim','city')},ensure_ascii=False,sort_keys=True).casefold()
    with _cache_lock:
        cached=_cache.get(key)
        if cached and not body.refresh and time.time()-cached['at']<_effective_cache_ttl(cached['value']):
            return {**cached['value'],'cached':True,'checked_at':cached['at'],'history_id':cached.get('id')}
    previous=saved(key,None)
    if previous and not body.refresh and time.time()-previous['at']<_effective_cache_ttl(previous['value']):
        return {**previous['value'],'cached':True,'checked_at':previous['at'],'history_id':previous['id']}
    client_key=_client_login_key(request)
    def work():
        _progress_ctx.id=body.request_id
        progress_report('در صف جست‌وجو',0,0)
        with _search_semaphore:
            progress_report('شروع بررسی',0,0)
            with _cache_lock:
                cached=_cache.get(key)
                if cached and not body.refresh and time.time()-cached['at']<_effective_cache_ttl(cached['value']):
                    return {**cached['value'],'cached':True,'checked_at':cached['at'],'history_id':cached.get('id')}
            try:
                enforce_rate(client_key)
                started=time.monotonic()
                value=research_market(vehicle)
                value['response_ms']=round((time.monotonic()-started)*1000)
                now=time.time()
                history_id=persist(query,key,value)
                with _cache_lock:
                    _cache[key]={'at':now,'value':value,'id':history_id}
                    if len(_cache)>200:
                        oldest=min(_cache,key=lambda k:_cache[k]['at'])
                        _cache.pop(oldest,None)
                progress_report('تکمیل شد',1,1)
                return {**value,'cached':False,'checked_at':now,'history_id':history_id}
            except RuntimeError:
                with _cache_lock:
                    old=_cache.get(key)
                if not old: old=saved(key,MAX_STALE_AGE)
                if old and _has_price_evidence(old['value']) and time.time()-old['at']<=MAX_STALE_AGE:
                    return {**old['value'],'cached':True,'stale':True,'checked_at':old['at'],'history_id':old.get('id'),
                            'warnings':old['value'].get('warnings',[])+['به دلیل محدودیت سرویس، آخرین نتیجه ذخیره‌شده نمایش داده می‌شود.']}
                raise
    try: return await asyncio.wait_for(asyncio.to_thread(work),timeout=105)
    except asyncio.TimeoutError:
        raise HTTPException(504,'جست‌وجو بیش از حد طول کشید؛ ممکن است بررسی منابع هنوز در سرور ادامه داشته باشد')
    except RuntimeError as e: raise HTTPException(502,str(e))
    except Exception:
        logging.exception('Search failure')
        raise HTTPException(502,'خطای پردازش پاسخ سرویس‌های خارجی')

@app.get('/api/history')
def history(limit:int=20,_=Depends(authorized)):
    limit=min(max(limit,1),100)
    with db() as c:
        rows=c.execute("SELECT id,query,created_at,result_json FROM searches WHERE cache_key NOT LIKE 'domain:%' ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    items=[]
    for row in rows:
        d=json.loads(row['result_json'])
        items.append({'id':row['id'],'query':row['query'],'checked_at':row['created_at'],'new':d.get('new'),'used':d.get('used'),'sources_count':len(d.get('sources',[]))})
    return {'items':items}
@app.get('/api/history/{item_id}')
def history_detail(item_id:int,_=Depends(authorized)):
    with db() as c: row=c.execute('SELECT * FROM searches WHERE id=?',(item_id,)).fetchone()
    if not row or row['cache_key'].startswith('domain:'): raise HTTPException(404,'گزارش پیدا نشد')
    return {**json.loads(row['result_json']),'history_id':row['id'],'checked_at':row['created_at'],'cached':True,'query':row['query']}
@app.post('/api/compare')
def compare(body:CompareInput,_=Depends(authorized)):
    marks=','.join('?' for _ in body.ids)
    with db() as c: rows=c.execute(f'SELECT * FROM searches WHERE id IN ({marks})',body.ids).fetchall()
    if len(rows)!=len(set(body.ids)) or any(r['cache_key'].startswith('domain:') for r in rows): raise HTTPException(404,'برخی گزارش‌ها پیدا نشدند')
    return {'items':[{'id':r['id'],'query':r['query'],'checked_at':r['created_at'],'new':json.loads(r['result_json']).get('new'),'used':json.loads(r['result_json']).get('used')} for r in rows]}

FRONTEND_DIST = Path(os.getenv('FRONTEND_DIST', str(Path(__file__).resolve().parent/'frontend'/'dist' if (Path(__file__).resolve().parent/'frontend'/'dist').is_dir() else Path(__file__).resolve().parent.parent/'frontend'/'dist')))
if (FRONTEND_DIST/'assets').is_dir():
    app.mount('/assets', StaticFiles(directory=str(FRONTEND_DIST/'assets')), name='assets')
@app.get('/{path:path}')
def spa(path:str):
    if path.startswith('api/'): raise HTTPException(404)
    index = FRONTEND_DIST/'index.html'
    if not index.is_file():
        raise HTTPException(503, 'رابط کاربری هنوز ساخته نشده است؛ در frontend دستور npm run build را اجرا کنید')
    return FileResponse(str(index))
