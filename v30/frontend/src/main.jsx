import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

const fa = n => new Intl.NumberFormat('fa-IR',{maximumFractionDigits:1}).format(n);
const money = value => {
  if(typeof value !== 'number' || !Number.isFinite(value))return '—';
  return value>=1e9 ? `${fa(value/1e9)} میلیارد تومان` : `${fa(value/1e6)} میلیون تومان`;
};
const date = iso => iso ? new Date(iso).toLocaleString('fa-IR',{dateStyle:'medium',timeStyle:'short'}) : '—';
const sources={divar:'دیوار',bama:'باما',sheypoor:'شیپور',hamrah:'همراه مکانیک',karnameh:'کارنامه',khodro45:'خودرو۴۵'};
const condition={new:'صفر کیلومتر',used:'کارکرده'};
const quality={high:'بالا',medium:'متوسط',low:'پایین'};

async function jsonFetch(url,options){
 let response;
 try{response=await fetch(url,{...options,headers:{...(options?.headers||{}),'Accept':'application/json'}})}
 catch{throw new Error('اتصال به سرور برقرار نشد؛ وضعیت برنامه در Liara را بررسی کنید.');}
 const contentType=response.headers.get('content-type')||'';
 let body={};
 if(contentType.includes('application/json')){
   try{body=await response.json()}catch{}
 }
 if(!response.ok){
   if([502,504].includes(response.status))throw new Error('سرور برنامه پاسخ نمی‌دهد (خطای '+response.status+'). راه‌اندازی Backend، پورت و گزارش‌های Liara بررسی شود.');
   if(response.status===503)throw new Error('سرویس قیمت موقتاً آماده نیست؛ اتصال PostgreSQL و تنظیم DATABASE_URL در Liara بررسی شود.');
   if(response.status===404)throw new Error('نسخه سایت و مسیر API هماهنگ نیستند؛ نسخه یکسان Frontend و Backend را منتشر کنید.');
   if(response.status===429)throw new Error('تعداد جست‌وجوها زیاد است؛ کمی بعد تلاش کنید.');
   throw new Error(typeof body.detail==='string'?body.detail:'دریافت پاسخ قیمت با خطای HTTP '+response.status+' انجام نشد.');
 }
 if(!contentType.includes('application/json'))throw new Error('API پاسخ JSON نداد؛ مسیر API یا نسخه منتشرشده را بررسی کنید.');
 return body;
}
function Icon({name,size=20}){
 const paths={search:<><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  arrow:<path d="M14 6l-6 6 6 6M9 12h12"/>,car:<><path d="M5 17h14l-1-7H6l-1 7Z"/><path d="M7 10l2-4h6l2 4M7 17v2M17 17v2M8 14h1M15 14h1"/></>,
  clock:<><circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/></>,
  link:<><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2"/></>,
  shield:<><path d="M12 2 4 5v7c0 5 3 8 8 10 5-2 8-5 8-10V5l-8-3Z"/><path d="m9 12 2 2 4-4"/></>,
  refresh:<><path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M5.5 9A7 7 0 0 1 18 7l2 5M4 12l2 5a7 7 0 0 0 12-2"/></>};
 return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function PriceCard({g}){
 const title=[g.year,g.trim,condition[g.condition]||'وضعیت نامشخص',g.transmission==='automatic'?'اتوماتیک':g.transmission==='manual'?'دستی':null].filter(Boolean).join(' · ');
 return <article className="result-card">
   <div className="result-card-top"><h3>{title}</h3><span className={'tag '+g.status}>{g.status==='fresh'?'به‌روز':'نیازمند به‌روزرسانی'}</span></div>
   <div className="range-label">بازه قیمت پیشنهادی آگهی‌های مشابه</div>
   <div className="range-price" dir="rtl">{money(g.low_toman)} <span className="to">تا</span> {money(g.high_toman)}</div>
   <div className="median">میانه قیمت: <strong>{money(g.median_toman)}</strong></div>
   <div className="facts">
    <div><b>{fa(g.sample_count)}</b><span>آگهی معتبر</span></div>
    <div><b>{fa(g.source_count)}</b><span>منبع مستقل</span></div>
    <div><b>{quality[g.confidence]||'محدود'}</b><span>کیفیت نمونه</span></div>
   </div>
   <p className="updated"><Icon name="clock" size={15}/>آخرین به‌روزرسانی: {date(g.updated_at)}</p>
   <div className="source-links">{(g.ads||[]).map(a=><a key={a.source+'-'+a.url} href={a.url} target="_blank" rel="noopener noreferrer"><Icon name="link" size={15}/>{sources[a.source]||a.source}</a>)}</div>
 </article>;
}

function Admin(){
 const [secret,setSecret]=useState(''),[state,setState]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function reload(){
  setBusy(true);setError('');try{setState(await jsonFetch('/api/v1/sources/status',{headers:{Authorization:'Bearer '+secret}}))}catch(e){setError(e.message)}finally{setBusy(false)}
 }
 async function toggle(src){
  setBusy(true);setError('');try{await jsonFetch('/api/v1/admin/sources/'+src.code,{method:'POST',headers:{Authorization:'Bearer '+secret,'Content-Type':'application/json'},body:JSON.stringify({enabled:!src.enabled})});await reload()}catch(e){setError(e.message)}finally{setBusy(false)}
 }
 async function update(){
  setBusy(true);setError('');try{await jsonFetch('/api/v1/admin/refresh',{method:'POST',headers:{Authorization:'Bearer '+secret}});setError('درخواست به‌روزرسانی ثبت شد. Worker آن را مستقل اجرا می‌کند.')}catch(e){setError(e.message)}finally{setBusy(false)}
 }
 return <section className="admin panel"><h2>وضعیت منابع — فقط مدیر</h2>
  <div className="admin-auth"><input value={secret} onChange={e=>setSecret(e.target.value)} type="password" autoComplete="off" placeholder="توکن مدیریت" aria-label="توکن مدیریت"/><button onClick={reload} disabled={busy||!secret}>مشاهده وضعیت</button></div>
  {error&&<p className="notice">{error}</p>}
  {state&&<><div className="admin-summary"><span>مدل‌های دارای بازه: {fa(state.priced_segments)}</span><span>آخرین اجرا: {date(state.last_scheduler_run?.started_at)}</span></div>
  <div className="source-statuses">{state.sources.map(s=><article key={s.code}>
   <div><strong>{s.name}</strong><span className={'status '+(s.enabled?'active':'disabled')}>{s.enabled?'فعال‌شده':'غیرفعال'}</span></div>
   <small>آخرین دریافت معتبر: {date(s.last_success_at)}</small>
   <small>آخرین تلاش: {date(s.last_attempt_at)} · دریافت: {s.fetched_count||0} · معتبر: {s.valid_count||0}</small>
   {s.last_error_code&&<small className="error">{s.last_error_code} — {s.last_error_detail||''}</small>}
   <button disabled={busy} onClick={()=>toggle(s)}>{s.enabled?'غیرفعال‌سازی':'فعال‌سازی'}</button>
  </article>)}</div><button className="outline" disabled={busy} onClick={update}><Icon name="refresh" size={16}/> درخواست به‌روزرسانی دستی</button></>}
 </section>;
}

function App(){
 const [q,setQ]=useState(''),[selection,setSelection]=useState(null),[suggestions,setSuggestions]=useState([]),
 [result,setResult]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[admin,setAdmin]=useState(false);
 const seq=useRef(0);
 useEffect(()=>{
  if(q.trim().length<2){setSuggestions([]);return}
  const current=++seq.current;
  const h=setTimeout(()=>{
   jsonFetch('/api/v1/vehicles/search?q='+encodeURIComponent(q)).then(data=>{if(seq.current===current)setSuggestions(data.suggestions||[])}).catch(()=>{})
  },230);return()=>clearTimeout(h);
 },[q]);
 async function search(chosen=null){
  const id=chosen?.id||selection?.id;
  if(!q.trim())return;
  setBusy(true);setError('');setResult(null);setSuggestions([]);
  const url='/api/v1/prices/estimate?q='+encodeURIComponent(q)+(id?'&vehicle_id='+encodeURIComponent(id):'');
  try{setResult(await jsonFetch(url))}catch(e){setError(e.message)}finally{setBusy(false)}
 }
 const choose=s=>{setQ(s.name);setSelection(s);setSuggestions([]);searchWith(s)};
 async function searchWith(s){
  setBusy(true);setError('');setResult(null);
  try{setResult(await jsonFetch('/api/v1/prices/estimate?q='+encodeURIComponent(s.name)+'&vehicle_id='+encodeURIComponent(s.id)))}catch(e){setError(e.message)}finally{setBusy(false)}
 }
 return <div className="app-shell">
   <header><a className="brand" href="/" aria-label="داودی‌کار"><span className="brand-mark"><Icon name="car" size={28}/></span><span>داودی<span className="gold">کار</span><small>پیدا کردن قیمت، به همین سادگی</small></span></a><a className="header-anchor" href="#search">جست‌وجوی قیمت خودرو <Icon name="arrow" size={16}/></a></header>
   <main><section className="hero" id="search"><span className="eyebrow"><Icon name="shield" size={16}/> قیمت از آگهی‌های قابل پیگیری</span>
     <h1>قیمت حدودی ماشینت رو <em>یک‌جا</em> پیدا کن.</h1>
     <p>فقط نام خودرو را بنویس. داودی‌کار بازه قیمت‌های ذخیره‌شده از آگهی‌های مشابه را نشان می‌دهد؛ بدون جست‌وجو در چند سایت.</p>
     <form onSubmit={e=>{e.preventDefault();search()}} className="search-box" autoComplete="off">
       <div className="search-main"><Icon name="search" size={25}/><input value={q} onChange={e=>{setQ(e.target.value);setSelection(null)}} placeholder="مثلاً سانتافه ۲۰۱۷ یا فیدلیتی پرایم" aria-label="نام خودرو" maxLength={100} required/>
         <button disabled={busy||q.trim().length<2} type="submit">{busy?'در حال دریافت…':'نمایش قیمت'}<Icon name="arrow" size={20}/></button></div>
       {suggestions.length>0&&<div className="suggestions" role="listbox">{suggestions.slice(0,6).map(s=><button type="button" role="option" aria-selected="false" key={s.id} onClick={()=>choose(s)}>{s.name}</button>)}</div>}
     </form>
     <div className="examples"><span>مثلاً:</span>{['سانتافه ۲۰۱۷','دنا پلاس توربو اتومات ۱۴۰۲','فیدلیتی پرایم','لیفان 820'].map(v=><button key={v} onClick={()=>{setQ(v);setSelection(null);setSuggestions([])}}>{v}</button>)}</div>
   </section>
   <section aria-live="polite" className="results">
    {error&&<div className="notice error"><strong>جست‌وجو انجام نشد.</strong> {error}</div>}
    {result&&<><div className="results-title"><h2>{result.vehicle||'نتیجه جست‌وجو'}</h2><p>{result.message}</p></div>
      {result.status==='needs_selection'&&<div className="choice panel"><h3>کدام خودرو را می‌خواهید؟</h3><div>{(result.options||[]).map(x=><button key={x.id} onClick={()=>choose(x)}>{x.name}</button>)}</div></div>}
      {result.status==='no_data'&&<div className="no-data panel"><Icon name="clock" size={30}/><h3>فعلاً داده معتبر کافی نداریم</h3><p>{result.message}</p><small>ثبت درخواست بررسی به معنی دریافت موفق قیمت نیست. نتیجه پس از به‌روزرسانی مستقل آماده می‌شود.</small></div>}
      {result.status==='ok'&&<><div className="cards">{result.groups.map(g=><PriceCard key={g.segment_key} g={g}/>)}</div><p className="disclaimer"><Icon name="shield" size={16}/> این قیمت‌ها از آگهی فروشندگان استخراج می‌شوند؛ قیمت قطعی معامله نیستند.</p></>}
    </>}
   </section>
   <section className="how"><div><span className="count">۰۱</span><h3>نام خودرو را وارد کنید</h3><p>فارسی یا انگلیسی، حتی بدون وارد کردن سال.</p></div><div><span className="count">۰۲</span><h3>مدل‌ها جدا بررسی می‌شوند</h3><p>سال، تیپ و وضعیت صفر یا کارکرده با هم مخلوط نمی‌شوند.</p></div><div><span className="count">۰۳</span><h3>قیمت و منبع را ببینید</h3><p>زمان به‌روزرسانی و لینک آگهی معتبر نمایش داده می‌شود.</p></div></section>
   </main><footer><p>داودی‌کار · جست‌وجوی ساده قیمت خودرو در ایران</p><button onClick={()=>setAdmin(v=>!v)}>{admin?'بستن مدیریت':'مدیریت منابع'}</button></footer>
   {admin&&<Admin/>}
 </div>;
}

createRoot(document.getElementById('root')).render(<App/>);
