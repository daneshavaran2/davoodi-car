/* Self-contained Node regression for the zero-dependency speech fallback + UX code. */
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../frontend/src/main.jsx'),'utf8');
const begin=source.indexOf('function localVoiceParse(text)');
const end=source.indexOf('\nfunction MarketDashboard',begin);
assert(begin>=0&&end>begin,'Frontend fallback parser must be present');
const context={};vm.createContext(context);vm.runInContext(source.slice(begin,end)+'\nthis.parse=localVoiceParse;',context,{timeout:1000});
const cases=[
  ['سانتافه نیوفیس مدل ۲۰۲۵ صفر کیلومتر',{brand:'هیوندای',model:'سانتافه',year:2025,mileage:0,is_new:true}],
  ['فیتیلی پرایم مدل ۱۴۰۳ کارکرد ۵۰ هزار کیلومتر',{brand:'بهمن موتور',model:'فیدلیتی',year:1403,mileage:50000,trim:'پرایم'}],
  ['پژو ۲۰۷ اتوماتیک مدل ۱۴۰۱ کارکرد ۵۰ هزار',{model:'۲۰۷',year:1401,mileage:50000,transmission:'اتوماتیک'}],
  ['سانتا فه مدل 2025 کارکرد 25000 کیلومتر',{model:'سانتافه',year:2025,mileage:25000}],
  ['خودرو بدون نام مدل ۲۰۲۵',{model:null,year:2025}],
  ['فیدلیتی مدل ۱۴۰۳',{model:'فیدلیتی',year:1403,mileage:null,needs_trim:true}],
];
for(const [phrase,expected] of cases){const actual=context.parse(phrase);for(const [key,val] of Object.entries(expected)){assert.equal(actual[key],val,phrase+' :: '+key+' '+JSON.stringify(actual))}}
assert(source.includes('refresh:forceRefresh'),'Refresh must explicitly bypass the cache');
assert(source.includes("search(null,lastQuery,null,true)"),'Refresh button must request a fresh search');
assert(source.includes('role="alert"'),'Errors must be announced to screen readers');
assert(source.includes('quick-examples'),'Search suggestions must be available');
assert(source.includes('detected-vehicle'),'Parsed model must be displayed');
console.log(`Frontend fallback ${cases.length} cases + 5 UX contracts: OK`);
