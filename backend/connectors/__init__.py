from . import bama, hamrah, khodro45, divar
from .browser import source_session

BUILTIN={
    'divar.ir': divar.search,
    'bama.ir': bama.search,
    'hamrah-mechanic.com': hamrah.search,
    'khodro45.com': khodro45.search,
}

def run(domain,vehicle,limit=30):
    fn=BUILTIN.get(domain)
    if fn is None: return None
    with source_session():
        return fn(vehicle,limit=limit)
