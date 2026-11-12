import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {makeQuickDecision} from '../frontend/src/quickDecision.mjs';

const main=readFileSync(new URL('../frontend/src/main.jsx',import.meta.url),'utf8');
const card=readFileSync(new URL('../frontend/src/QuickVerdict.jsx',import.meta.url),'utf8');
const groups=readFileSync(new URL('../frontend/src/ModelOverview.jsx',import.meta.url),'utf8');
assert.ok(main.includes('search(null,finalText,null)'), 'Voice must start a search without an extra confirmation');
assert.ok(main.includes('فقط نام خودرو؛ مثلاً فیدلیتی'), 'Manual input should require only a model name');
assert.ok(card.includes('<ModelOverview overview={overview}/>'), 'Grouped prices should be the main answer');
assert.ok(groups.includes('price_min===g.price_max'), 'A single observed price must not become an invented wide range');
assert.ok(groups.includes('آگهی'), 'Each group must show its observed advertisement count');
assert.ok(groups.includes('a.source||a.domain'), 'Each group must show the real source name');
assert.ok(groups.includes('a.url'), 'Each group must show verified evidence links');
assert.ok(!groups.includes('Math.random'), 'Never manufacture estimate values');
const broad={vehicle:{brand:'بهمن موتور',model:'فیدلیتی',year:null,mileage:null},
 model_overview:{mode:'name_only',groups:[{label:'۱۴۰۳ · پرایم · کارکرده',price_min:2_400_000_000,price_max:2_600_000_000}]}};
const d=makeQuickDecision(broad);
assert.equal(d.estimate,null, 'No single average across unspecified years and trims');
assert.equal(d.kind,'limited');
assert.ok(d.heading.includes('بازه'));
const empty=makeQuickDecision({...broad,model_overview:{mode:'name_only',groups:[]}});
assert.equal(empty.kind,'empty');
console.log('v28 model-name-only UX contracts OK');
