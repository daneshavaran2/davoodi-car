const fs=require('fs');const assert=require('assert');
const main=fs.readFileSync('frontend/src/main.jsx','utf8');
const css=fs.readFileSync('frontend/src/style.css','utf8');
const checks=[
['Actual progress endpoint',main.includes('/api/search-progress/')],
['Authenticated source progress fetch',main.includes("Authorization:'Bearer '+token")],
['No fake timed progress',!main.includes('setProgress(p=>Math.min(92')],
['Source progress visible',main.includes("searchStage||'در انتظار پاسخ منابع بازار...")],
['Manual and voice tabs',main.includes('ورود دستی')&&main.includes('ورود با صدا')],
['Source table and distribution',main.includes('intel-source-table')&&main.includes('intel-bars')],
['Farsi accessibility',main.includes('aria-label="نام خودرو"')],
['Mobile touch targets',css.includes('min-height:48px')],
['Reduced motion support',css.includes('prefers-reduced-motion:reduce')],
['Photo blob URL release',main.includes('URL.revokeObjectURL(photoObjectUrl)')],
];for(const [name,ok] of checks){assert(ok, name)}
console.log(`v24 UI static contracts: ${checks.length}/${checks.length} OK`);
