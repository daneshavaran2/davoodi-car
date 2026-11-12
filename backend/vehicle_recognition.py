"""Persian vehicle name recognition with conservative fuzzy suggestions.

No network calls and no invented vehicle prices. Use the result as a candidate,
not as proof of a vehicle's exact trim, year or manufacturer.
"""
import re
from difflib import SequenceMatcher

ALIASES={
    "فیدلیتی": ["فیدلیتی","فیدیلیتی","فیتیلی","فیدلیتى","فیدیلتی","فیدلیتی پرایم","فیدلیتی پرستیژ","fidelity","fidility","fideli ty"],
    "دیگنیتی": ["دیگنیتی","دیگنیتی پرایم","دیگنیتی پرستیژ","dignity"],
    "تیگو 7": ["تیگو هفت","تیگو ۷","تیگو 7","tiggo 7","tiggo7"],
    "تیگو 8": ["تیگو هشت","تیگو ۸","تیگو 8","tiggo 8","tiggo8"],
    "فونیکس FX": ["فونیکس اف ایکس","فونیکس fx","fownix fx","fx"],
    "هایما S7": ["هایما اس هفت","هایما s7","haima s7"],
    "لاماری ایما": ["لاماری ایما","لاماری","lamari eama","lamari eama"],
    "کی ام سی J7": ["کی ام سی جی هفت","kmc j7","کی ام سی j7"],
}
MAKER={
    "فیدلیتی":"بهمن موتور","دیگنیتی":"بهمن موتور",
    "تیگو 7":"مدیران خودرو / چری","تیگو 8":"مدیران خودرو / چری",
    "فونیکس FX":"مدیران خودرو / فونیکس",
    "هایما S7":"ایران خودرو / هایما",
    "لاماری ایما":"آرین پارس موتور / لاماری",
    "کی ام سی J7":"کرمان موتور / KMC",
}
NORMAL_MAP=str.maketrans("يكىۀةأإآ۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩","یکییههااا01234567890123456789")
def normalize(s):
    s=str(s or "").lower().translate(NORMAL_MAP)
    s=re.sub(r"[^\w\s]"," ",s,flags=re.UNICODE)
    return re.sub(r"\s+"," ",s).strip()

def recognize_vehicle(text,threshold=.76):
    """Return candidate with confidence and explicit confirmation flag."""
    query=normalize(text)
    if not query:return {"status":"missing","brand":None,"model":None,"manufacturer":None,"confidence":0,"requires_confirmation":True}
    best=None
    for model,aliases in ALIASES.items():
        for alias in aliases:
            a=normalize(alias)
            exact=bool(re.search(r"(?<!\w)"+re.escape(a)+r"(?!\w)",query))
            similarity=max((SequenceMatcher(None,a,part).ratio() for part in [query]+[query[i:j] for i in range(len(query.split())) for j in []]),default=0)
            # compare against all contiguous word spans of roughly matching length
            words=query.split()
            for length in range(max(1,len(a.split())-1),min(len(words),len(a.split())+1)+1):
                for i in range(len(words)-length+1):
                    similarity=max(similarity,SequenceMatcher(None,a," ".join(words[i:i+length])).ratio())
            score=1.0 if exact else similarity
            if best is None or score>best[0]:best=(score,model,alias)
    score,model,matched=best
    if score<threshold:
        return {"status":"unknown","brand":None,"model":None,"manufacturer":None,"confidence":round(score,3),"requires_confirmation":True}
    brand="فیدلیتی" if model=="فیدلیتی" else model.split()[0]
    return {"status":"candidate","brand":brand,"model":model,"manufacturer":MAKER.get(model),"confidence":round(score,3),"matched_alias":matched,"requires_confirmation":True,
            "message":f"آیا منظورتان {model} است؟"}
