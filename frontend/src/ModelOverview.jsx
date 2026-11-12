import React from 'react';
import {ExternalLink,Info} from 'lucide-react';
import {moneyFa} from './quickDecision.mjs';

export default function ModelOverview({overview}){
 const groups=Array.isArray(overview?.groups)?overview.groups:[];
 if(!groups.length)return <div className="quick-no-quote">
   <Info size={22}/><strong>فعلاً آگهی معتبر کافی برای نمایش قیمت پیدا نشد.</strong>
   <small>این موضوع به معنی نبود خودرو در بازار نیست؛ وضعیت منابع را در بخش پایین صفحه ببینید.</small>
 </div>;
 return <section className="simple-price-groups" aria-label="بازه قیمت انواع خودرو">
   <p className="simple-price-intro">قیمت‌های پیشنهادی آگهی‌های پیدا شده؛ سال و تیپ‌های متفاوت جدا شده‌اند.</p>
   <div className="simple-price-grid">
    {groups.slice(0,6).map((g,i)=><article className="simple-price-item" key={String(g.year)+'-'+g.trim+'-'+g.condition+'-'+i}>
     <div className="simple-price-item-head">
      <strong>{g.label}</strong>
      <small>{Number(g.listing_count||0).toLocaleString('fa-IR')} آگهی</small>
     </div>
     <div className="simple-price-value">
      {g.price_min===g.price_max?moneyFa(g.price_min):moneyFa(g.price_min)+' تا '+moneyFa(g.price_max)}
     </div>
     {g.limited&&<small className="simple-price-limited">نمونه محدود؛ فقط قیمت درج‌شده در آگهی‌ها</small>}
     <div className="simple-price-links">
      {(g.ads||[]).slice(0,3).filter(a=>a&&typeof a.url==='string'&&/^https:\/\//.test(a.url)).map((a,j)=>
       <a key={a.url+j} href={a.url} target="_blank" rel="noopener noreferrer">{a.source||a.domain||'آگهی'} <ExternalLink size={13}/></a>)}
     </div>
    </article>)}
   </div>
   {overview.groups_total>groups.length&&<small>{Number(overview.groups_total-groups.length).toLocaleString('fa-IR')} گروه دیگر وجود دارد؛ برای محدودکردن نتیجه، سال یا تیپ را اضافه کنید.</small>}
   <small className="simple-price-note">{overview.note||'قیمت پیشنهادی فروشنده، الزاماً قیمت معامله نیست.'}</small>
 </section>;
}
