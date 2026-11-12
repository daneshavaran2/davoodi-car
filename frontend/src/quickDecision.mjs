/** Evidence-only three-second decision model. No model-generated prices. */
export const moneyFa = value => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '—';
  const billions = value / 1_000_000_000;
  if (billions >= 0.1) return new Intl.NumberFormat('fa-IR',{maximumFractionDigits:2}).format(billions) + ' میلیارد تومان';
  return new Intl.NumberFormat('fa-IR',{maximumFractionDigits:0}).format(value) + ' تومان';
};

export function makeQuickDecision(result) {
  const v = result?.vehicle || {};
  const broad=result?.model_overview?.mode==='name_only';
  const broadGroups=Array.isArray(result?.model_overview?.groups)?result.model_overview.groups:[];
  const newCar = v.mileage === 0;
  const usedCar = typeof v.mileage === 'number' && v.mileage > 0;
  const group = newCar ? 'new' : usedCar ? 'used' : null;
  const stats = group ? result?.[group] || {} : {};
  const count = Number(stats.sample_count) || 0;
  const listings = Number(stats.listing_count) || 0;
  const domains = Number(stats.domain_count) || 0;
  const score = Number.isFinite(Number(stats.confidence_score)) ? Math.min(100,Math.max(0,Math.round(Number(stats.confidence_score)))) : null;
  const estimate = stats.price_average;
  // Market estimates require enough real ads; reference-only or 1-2 results are not sufficient.
  const priced = Boolean(v.model) && group !== null && count >= 3 && listings >= 2 && typeof estimate === 'number' && Number.isFinite(estimate) && estimate > 0;
  const min = stats.suggested_min;
  const max = stats.suggested_max;
  const validRange = priced && typeof min === 'number' && typeof max === 'number' && min > 0 && max >= min;
  // In sparse markets show only verified asking prices actually visible in
  // accepted direct sale listings. This is NOT an estimated transaction price.
  // Group URLs come from the backend's accepted after-filter sample.
  const acceptedUrls = new Set(stats.used_source_urls || []);
  const directListings = group && v.model ? (result?.sources || []).filter(s =>
    s?.accepted === true && s.kind === 'listing' && acceptedUrls.has(s.url) &&
    typeof s.url === 'string' && /^https:\/\//.test(s.url) &&
    typeof s.price === 'number' && Number.isFinite(s.price) &&
    s.price >= 50_000_000 && s.price <= 100_000_000_000) : [];
  const observedPrices = directListings.map(s=>s.price).sort((a,b)=>a-b);
  const observed = !priced && observedPrices.length
    ? {min:observedPrices[0],max:observedPrices[observedPrices.length-1],count:observedPrices.length}
    : null;
  const limited = group !== null && count > 0 && !priced;
  const stale = Boolean(result?.stale);
  const kind = broad ? (broadGroups.length?'limited':'empty') : !group ? 'need-details' : priced ? (stale ? 'stale' : 'priced') : limited ? 'limited' : 'empty';
  const heading = broad ? (broadGroups.length?'بازه قیمت آگهی‌های خودرو':'قیمت آگهی‌های این مدل پیدا نشد') : !group ? 'کارکرد خودرو را مشخص کنید' : priced ? (stale ? 'بازه حدودی ذخیره‌شده' : 'بازه حدودی قیمت بازار') : observed ? 'قیمت آگهی‌های مشابه' : limited ? 'اطلاعات قیمت محدود است' : 'قیمت قابل استناد پیدا نشد';
  const next = broad ? (broadGroups.length?'برای مقایسه دقیق‌تر، سال یا تیپ را هم می‌توانید اضافه کنید.':'دسترسی به منابع یا وجود آگهی مرتبط را بررسی کنید؛ نبود نتیجه به معنی نبود خودرو در بازار نیست.')
    : !group ? 'کارکرد را وارد کنید یا عبارت «صفر کیلومتر» را بنویسید.'
    : priced && !stale ? 'پیش از معامله، مشخصات آگهی‌ها را با خودروی واقعی تطبیق دهید.'
    : stale ? 'برای قیمت جدید از دکمه «استعلام مجدد» استفاده کنید.'
    : observed ? 'این مبلغ فقط قیمت پیشنهادی فروشندگان است، نه قیمت قطعی معامله.' 
    : limited ? 'آگهی کافی برای نمایش قیمت حدودی پیدا نشد؛ منابع را بررسی کنید.'
    : 'مدل، سال، تیپ و وضعیت خودرو را بررسی یا استعلام را تازه‌سازی کنید.';
  const title = [v.brand,v.model,v.trim,v.year].filter(x=>x!==null&&x!==undefined&&x!=='').join(' · ');
  // In a limited report, show all accepted listing/market-price URLs instead of invented estimates.
  const evidence = group ? (result?.sources || []).filter(s => s && s.accepted &&
    (acceptedUrls.has(s.url) || !priced) && (s.kind === 'listing' || s.kind === 'market_price') &&
    typeof s.url === 'string' && /^https:\/\//.test(s.url)) : [];
  const evidenceLinks = evidence.slice(0,2).map(s=>({title:s.category||s.domain||'منبع بازار',url:s.url}));
  return {kind,group,title,heading,next,estimate:priced?estimate:null,observed,
    range:validRange?{min,max}:null,median:priced&&typeof stats.price_median==='number'?stats.price_median:null,
    listings,domains,count,score,quality:stats.confidence||'نامشخص',evidenceLinks,
    cached:Boolean(result?.cached),stale,checkedAt:result?.checked_at??null,
    responseMs:typeof result?.response_ms==='number'?result.response_ms:null};
}
