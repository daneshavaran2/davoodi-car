/** Evidence-only three-second decision model. No model-generated prices. */
export const moneyFa = value => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '—';
  const billions = value / 1_000_000_000;
  if (billions >= 0.1) return new Intl.NumberFormat('fa-IR',{maximumFractionDigits:2}).format(billions) + ' میلیارد تومان';
  return new Intl.NumberFormat('fa-IR',{maximumFractionDigits:0}).format(value) + ' تومان';
};

export function makeQuickDecision(result) {
  const v = result?.vehicle || {};
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
  const limited = group !== null && count > 0 && !priced;
  const stale = Boolean(result?.stale);
  const kind = !group ? 'need-details' : priced ? (stale ? 'stale' : 'priced') : limited ? 'limited' : 'empty';
  const heading = !group ? 'اول وضعیت صفر یا کارکرده را مشخص کنید' : priced ? (stale ? 'قیمت ذخیره‌شده؛ نیازمند بررسی مجدد' : 'برآورد بازار آماده است') : limited ? 'شواهد بازار محدود است' : 'قیمت قابل اتکا پیدا نشد';
  const next = !group ? 'کارکرد را وارد کنید یا عبارت «صفر کیلومتر» را بنویسید.'
    : priced && !stale ? 'پیش از معامله، مشخصات آگهی‌ها را با خودروی واقعی تطبیق دهید.'
    : stale ? 'برای قیمت جدید از دکمه «استعلام مجدد» استفاده کنید.'
    : limited ? 'نمونه کافی برای اعلام قیمت بازار وجود ندارد؛ شواهد را جداگانه بررسی کنید.'
    : 'مدل، سال، تیپ و وضعیت خودرو را بررسی یا استعلام را تازه‌سازی کنید.';
  const title = [v.brand,v.model,v.trim,v.year].filter(x=>x!==null&&x!==undefined&&x!=='').join(' · ');
  const acceptedUrls = new Set(stats.used_source_urls || []);
  // In a limited report, show all accepted listing/market-price URLs instead of invented estimates.
  const evidence = group ? (result?.sources || []).filter(s => s && s.accepted &&
    (acceptedUrls.has(s.url) || !priced) && (s.kind === 'listing' || s.kind === 'market_price') &&
    typeof s.url === 'string' && /^https:\/\//.test(s.url)) : [];
  const evidenceLinks = evidence.slice(0,2).map(s=>({title:s.category||s.domain||'منبع بازار',url:s.url}));
  return {kind,group,title,heading,next,estimate:priced?estimate:null,
    range:validRange?{min,max}:null,median:priced&&typeof stats.price_median==='number'?stats.price_median:null,
    listings,domains,count,score,quality:stats.confidence||'نامشخص',evidenceLinks,
    cached:Boolean(result?.cached),stale,checkedAt:result?.checked_at??null,
    responseMs:typeof result?.response_ms==='number'?result.response_ms:null};
}
