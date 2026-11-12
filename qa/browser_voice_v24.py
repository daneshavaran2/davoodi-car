"""Tests the *actual fallback parser JS* inside real headless Chromium.
Not a React/Vite UI build test; npm dependencies were unavailable offline.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright
src=Path(__file__).resolve().parent.parent/'frontend/src/main.jsx'
text=src.read_text()
a=text.index('function localVoiceParse(text){')
b=text.index('function MarketDashboard',a)
fn=text[a:b]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':390,'height':844},locale='fa-IR')
    page.set_content('<html lang="fa" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"/><body><input aria-label="نام خودرو"/></body></html>')
    samples=['فیتیلی پرایم مدل ۱۴۰۳ کارکرد ۵۰ هزار کیلومتر بدون رنگ',
             'سانتافه نیوفیس مدل ۲۰۲۵ صفر کیلومتر سفید اتوماتیک',
             'سانتافه مدل ۲۰۲۵ کارکرد ۵۰ هزار کیلومتر تحویل فوری']
    result=page.evaluate('''(args) => {'''+fn+''' return args.map(t=>localVoiceParse(t));}''',samples)
    assert result[0]['model']=='فیدلیتی' and result[0]['mileage']==50000,result
    assert result[0]['year']==1403 and result[0]['trim']=='پرایم',result
    assert result[1]['model']=='سانتافه' and result[1]['year']==2025 and result[1]['mileage']==0,result
    assert result[2]['mileage']==50000 and not result[2]['is_new'],result
    assert page.evaluate('innerWidth')==390
    page.set_viewport_size({'width':1440,'height':900})
    assert page.evaluate('innerWidth')==1440
    print('Chromium client-side voice fallback & viewport smoke PASS (3 speech phrases + 2 viewports)')
    browser.close()
