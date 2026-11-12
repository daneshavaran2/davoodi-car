"""Conservative Persian STT vehicle identification with explainable suggestions.

Not a generative classifier: fuzzy results must be confirmed by the user.
"""
import re
from difflib import SequenceMatcher

_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')

ALIASES = {
    ('بهمن موتور','فیدلیتی'): ('فیدلیتی','فیتیلی','فیدیلیتی','فیدیلتی','فیدلیتى','فدلیتی','فیدلیتیی','fidelity','fidility'),
    ('بهمن موتور','دیگنیتی'): ('دیگنیتی','دگنیتی','dignity'),
    ('هیوندای','سانتافه'): ('سانتافه','سانتافه نیوفیس','سانتافه نیو فیس','سانتا فه','سانتافایه','santa fe','santafe','santafee'),
    ('هیوندای','توسان'): ('توسان','توسون','tucson'),
    ('چری','تیگو ۷'): ('تیگو هفت','تیگو 7','tiggo 7'),
    ('چری','تیگو ۸'): ('تیگو هشت','تیگو 8','tiggo 8'),
    ('کیا','اسپورتیج'): ('اسپورتیج','اسپورتج','sportage'),
    ('تویوتا','کمری'): ('کمری','camry'),
    ('لاماری','ایما'): ('لاماری ایما','لاماری اما','lamari eama'),
    ('کرمان موتور','کی ام سی جی ۷'): ('کی ام سی جی هفت','کی ام سی j7','kmc j7'),
}

def norm(t):
    t = str(t or '').lower().translate(_DIGITS).replace('ي','ی').replace('ك','ک').replace('‌',' ')
    return re.sub(r'\s+',' ',re.sub(r'[^\w\s]',' ',t)).strip()

def _contains(text, alias):
    return bool(re.search(r'(?<!\w)'+re.escape(norm(alias))+r'(?!\w)',text))

def identify_vehicle(text, *, min_fuzzy=.83):
    t=norm(text)
    matches = [(len(norm(alias)), brand, model, alias) for (brand,model),aliases in ALIASES.items() for alias in aliases if _contains(t,alias)]
    if matches:
        _,brand,model,alias=max(matches)
        return {'brand':brand,'model':model,'confidence':1.0,'alias':alias,'type':'alias','requires_confirmation': norm(alias)!=norm(model)}
    words=t.split()
    candidates=[]
    for (brand,model),aliases in ALIASES.items():
        for alias in aliases:
            a=norm(alias)
            size=len(a.split())
            for window in range(max(1,size-1),min(len(words),size+1)+1):
                for i in range(len(words)-window+1):
                    segment=' '.join(words[i:i+window])
                    if min(len(segment),len(a))<4:continue
                    similarity=SequenceMatcher(None,a,segment).ratio()
                    if similarity>=min_fuzzy:
                        candidates.append((similarity,brand,model,segment))
    if not candidates:return None
    candidates.sort(reverse=True)
    best=candidates[0]
    # Avoid automatically assigning a fuzzy/near-homophone model.
    return {'brand':best[1],'model':best[2], 'confidence':round(best[0],2),
            'alias':best[3],'type':'fuzzy_suggestion','requires_confirmation':True}


def generation_from_text(text):
    t=norm(text)
    if re.search(r'نیو\s*فیس|new\s*face|فیس\s*لیفت',t):
        return 'نیوفیس'
    return None


def variant_from_text(text, model):
    t=norm(text)
    if model=='فیدلیتی':
        for trim in ('پرستیژ','پرایم','الیت','ایکس ۳'):
            if norm(trim) in t:return trim
    return None
