import React from 'react';
import {ArrowUpLeft,Clock3,Info,RotateCcw,ShieldCheck} from 'lucide-react';
import {makeQuickDecision,moneyFa} from './quickDecision.mjs';

export default function QuickVerdict({result,onRefresh,onEdit}){
  const decision=makeQuickDecision(result);
  const quote=decision.estimate!==null;
  const date=typeof decision.checkedAt==='number' ? new Date(decision.checkedAt*1000).toLocaleString('fa-IR') : null;
  return <section className={'quick-verdict '+decision.kind} aria-label="نتیجه در یک نگاه" aria-live="polite">
    <div className="quick-verdict-top">
      <span className="quick-eyebrow">نتیجه در یک نگاه</span>
      <span className="quick-data-label"><ShieldCheck size={15}/> {decision.stale?'اطلاعات ذخیره‌شده قدیمی':decision.cached?'نتیجه ذخیره‌شده':'براساس شواهد قابل پیگیری'}</span>
    </div>
    {decision.title&&<p className="quick-vehicle">{decision.title} · {decision.group==='new'?'صفر کیلومتر':decision.group==='used'?'کارکرده':'کارکرد نامشخص'}</p>}
    <h2 className="quick-decision-heading">{decision.heading}</h2>
    {quote ? <div className="quick-main-figure"><span>برآورد مرکزی بازار</span><strong data-testid="quick-quote">{moneyFa(decision.estimate)}</strong>
      {decision.range&&<p>بازه پیشنهادی: <b>{moneyFa(decision.range.min)} تا {moneyFa(decision.range.max)}</b></p>}
    </div>:<div className="quick-no-quote"><Info size={23}/><strong>برای این خودرو، قیمت تخمینی بدون پشتوانه نمایش داده نمی‌شود.</strong></div>}
    <div className="quick-facts">
      <span><b>{decision.listings.toLocaleString('fa-IR')}</b> آگهی واقعی</span>
      <span><b>{decision.domains.toLocaleString('fa-IR')}</b> منبع مستقل</span>
      <span><b>{decision.score===null?'نامشخص':decision.score.toLocaleString('fa-IR')+' / ۱۰۰'}</b> کیفیت داده</span>
    </div>
    <p className="quick-next"><b>قدم بعدی:</b> {decision.next}</p>
    {decision.evidenceLinks.length>0&&<div className="quick-source-links" aria-label="نمونه منابع معتبر">{decision.evidenceLinks.map(s=><a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer">{s.title}<ArrowUpLeft size={14}/></a>)}</div>}
    <div className="quick-bottom">
      <span><Clock3 size={14}/> {date ? 'آخرین بررسی: '+date : 'زمان بررسی نامشخص'} {decision.cached?'· از حافظه':''}</span>
      <div className="quick-buttons"><button type="button" onClick={onEdit}>اصلاح مشخصات</button><button type="button" onClick={onRefresh}><RotateCcw size={14}/> استعلام تازه</button></div>
    </div>
    <small className="quick-disclaimer">شاخص کیفیت، احتمال درست بودن قیمت نیست. قیمت آگهی الزاماً قیمت معامله نیست.</small>
  </section>;
}
