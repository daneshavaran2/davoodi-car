import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {makeQuickDecision,moneyFa} from '../frontend/src/quickDecision.mjs';
const TEST_URL='https://bama.ir/car/detail-trusted-one';
const v={brand:'بهمن موتور',model:'فیدلیتی',trim:'پرایم',year:1403,mileage:50000};
const sources=[{url:TEST_URL,accepted:true,kind:'listing',category:'باما'}];
const good={vehicle:v,used:{sample_count:6,listing_count:5,reference_count:1,domain_count:3,confidence_score:82,confidence:'متوسط',price_average:5_950_000_000,price_median:5_900_000_000,suggested_min:5_800_000_000,suggested_max:6_100_000_000,used_source_urls:[TEST_URL]},sources,checked_at:1794500000};
const decision=makeQuickDecision(good);
assert.equal(decision.kind,'priced');
assert.equal(decision.estimate,5_950_000_000);
assert.equal(decision.count,6);
assert.equal(decision.score,82);
assert.equal(decision.evidenceLinks[0].url,TEST_URL);
assert.equal(decision.range.min,5_800_000_000);
assert.ok(moneyFa(5_950_000_000).includes('میلیارد'));
// Two listings, even with a stray average field: never release a market estimate.
const limited=makeQuickDecision({...good,used:{...good.used,sample_count:2,listing_count:2}});
assert.equal(limited.kind,'limited'); assert.equal(limited.estimate,null);
// Simple-price view: show observed asking prices, not an invented market quote.
const sparseUrls=['https://bama.ir/car/detail-111','https://bama.ir/car/detail-222'];
const sparse=makeQuickDecision({...good,used:{sample_count:2,listing_count:2,domain_count:1,price_average:null,used_source_urls:sparseUrls},
  sources:sparseUrls.map((url,i)=>({url,kind:'listing',accepted:true,price:[2_400_000_000,2_600_000_000][i],category:'باما'}))});
assert.equal(sparse.estimate,null);
assert.deepEqual(sparse.observed,{min:2_400_000_000,max:2_600_000_000,count:2});
const single=makeQuickDecision({...good,used:{sample_count:1,listing_count:1,price_average:null,used_source_urls:[sparseUrls[0]]},
  sources:[{url:sparseUrls[0],kind:'listing',accepted:true,price:2_400_000_000}]});
assert.deepEqual(single.observed,{min:2_400_000_000,max:2_400_000_000,count:1});
const untrusted=makeQuickDecision({...good,used:{sample_count:1,listing_count:1,price_average:null,used_source_urls:[sparseUrls[0]]},
  sources:[{url:sparseUrls[0],kind:'listing',accepted:false,price:9_000_000_000}]});
assert.equal(untrusted.observed,null);
// Unknown model cannot be assigned a quote from a past/corrupt cached result.
const missingModel=makeQuickDecision({...good,vehicle:{...v,model:null}});
assert.equal(missingModel.estimate,null);
// Reference-only market prices are insufficient for a dealer-grade quote.
const references=makeQuickDecision({...good,used:{...good.used,sample_count:5,listing_count:0,reference_count:5}});
assert.equal(references.kind,'limited'); assert.equal(references.estimate,null);
// Unknown zero/used status: don't silently report the used category.
const unknown=makeQuickDecision({...good,vehicle:{...v,mileage:null}});
assert.equal(unknown.kind,'need-details');assert.equal(unknown.estimate,null);
const empty=makeQuickDecision({...good,used:{sample_count:0,listing_count:0,domain_count:0}});
assert.equal(empty.kind,'empty');assert.equal(empty.estimate,null);
const stale=makeQuickDecision({...good,stale:true,cached:true});
assert.equal(stale.kind,'stale');assert.equal(stale.stale,true);
// Input prices must be actual finite numbers, no implicit string coercion.
const injected=makeQuickDecision({...good,used:{...good.used,price_average:'999999999999'}});
assert.equal(injected.estimate,null);
// Evidence links must be real accepted HTTPS URLs.
const badUrl=makeQuickDecision({...good,sources:[{url:'javascript:alert(1)',kind:'listing',accepted:true}]});
assert.equal(badUrl.evidenceLinks.length,0);
const main=readFileSync(new URL('../frontend/src/main.jsx',import.meta.url),'utf8');
const component=readFileSync(new URL('../frontend/src/QuickVerdict.jsx',import.meta.url),'utf8');
const css=readFileSync(new URL('../frontend/src/style.css',import.meta.url),'utf8');
assert.ok(main.includes('<QuickVerdict result={result}'));
assert.ok(main.includes('<details className="deep-report"'));
assert.ok(component.includes('نتیجه در یک نگاه'));
assert.ok(component.includes('aria-live="polite"'));
assert.ok(css.includes('@media(max-width:620px){.quick-verdict'));
assert.ok(main.indexOf('<QuickVerdict result={result}')<main.indexOf('<MarketDashboard result={result}'));
console.log('quick price decision: market estimate + sparse asking-price safety scenarios OK');
