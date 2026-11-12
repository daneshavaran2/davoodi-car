from . import bama, hamrah, khodro45

BUILTIN={
    'bama.ir': bama.search,
    'hamrah-mechanic.com': hamrah.search,
    'khodro45.com': khodro45.search,
}

def run(domain,vehicle,limit=30):
    fn=BUILTIN.get(domain)
    return None if fn is None else fn(vehicle,limit=limit)
