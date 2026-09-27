import re, hashlib, sys, math
src = open("libgpod/src/itdb_hash58.c").read()
def table(name):
    m = re.search(r"static const unsigned char %s\[\d+\] = \{(.*?)\};" % name, src, re.S)
    return bytes(int(x,16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))
t1, t2, fixed = table("table1"), table("table2"), table("fixed")
assert len(t1)==256 and len(t2)==256 and len(fixed)==18
def lcm(a,b):
    if a==0 or b==0: return 1
    return a*b//math.gcd(a,b)
def generate_key(fwid):
    y = bytearray()
    for i in range(4):
        l = lcm(fwid[2*i], fwid[2*i+1]); hi, lo = (l>>8)&0xff, l&0xff
        y += bytes([t1[hi], t2[hi], t1[lo], t2[lo]])
    key = bytearray(64); key[:20] = hashlib.sha1(fixed + y).digest()
    return key
def hash58(fwid, data):
    key = generate_key(fwid)
    inner = hashlib.sha1(bytes(k^0x36 for k in key) + data).digest()
    return hashlib.sha1(bytes(k^0x5c for k in key) + inner).digest()
path = sys.argv[1]; fwid = bytes.fromhex(sys.argv[2])
d = bytearray(open(path,"rb").read())
assert d[:4]==b"mhbd"
stored = bytes(d[0x58:0x6c]); scheme = int.from_bytes(d[0x30:0x32],"little")
print("stored hashing_scheme:", scheme, " unk_0x70:", int.from_bytes(d[0x70:0x72],"little"), " hash72 prefix:", d[0x72:0x74].hex())
d[0x18:0x20] = bytes(8); d[0x32:0x46] = bytes(20); d[0x58:0x6c] = bytes(20); d[0x30:0x32] = (1).to_bytes(2,"little")
calc = hash58(fwid, bytes(d))
print("stored hash58:", stored.hex()); print("calc   hash58:", calc.hex()); print("MATCH" if calc==stored else "MISMATCH")
