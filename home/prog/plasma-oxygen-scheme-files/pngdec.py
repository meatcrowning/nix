import struct, zlib
def png_rgba(data):
    if data[:8]!=b'\x89PNG\r\n\x1a\n': return None
    pos=8; idat=b''; w=h=bd=ct=None; plte=None; trns=None
    while pos<len(data):
        ln=struct.unpack('>I',data[pos:pos+4])[0]; typ=data[pos+4:pos+8]
        chunk=data[pos+8:pos+8+ln]; pos+=12+ln
        if typ==b'IHDR': w,h,bd,ct=struct.unpack('>IIBB',chunk[:10])
        elif typ==b'IDAT': idat+=chunk
        elif typ==b'PLTE': plte=chunk
        elif typ==b'tRNS': trns=chunk
        elif typ==b'IEND': break
    if bd!=8: return None
    ch={0:1,2:3,3:1,4:2,6:4}.get(ct)
    if ch is None: return None
    raw=zlib.decompress(idat); stride=w*ch; out=[]; prev=bytearray(stride); i=0
    for y in range(h):
        ft=raw[i]; i+=1; line=bytearray(raw[i:i+stride]); i+=stride
        for x in range(stride):
            a=line[x-ch] if x>=ch else 0; b=prev[x]; c=prev[x-ch] if x>=ch else 0
            if ft==1: line[x]=(line[x]+a)&255
            elif ft==2: line[x]=(line[x]+b)&255
            elif ft==3: line[x]=(line[x]+((a+b)>>1))&255
            elif ft==4:
                p=a+b-c; pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
                pr=a if (pa<=pb and pa<=pc) else (b if pb<=pc else c)
                line[x]=(line[x]+pr)&255
        prev=line
        for x in range(w):
            px=line[x*ch:(x+1)*ch]
            if ct==6: out.append(tuple(px))
            elif ct==2: out.append((px[0],px[1],px[2],255))
            elif ct==0: out.append((px[0],px[0],px[0],255))
            elif ct==4: out.append((px[0],px[0],px[0],px[1]))
            elif ct==3:
                idx=px[0]; r,g,b=plte[idx*3:idx*3+3]
                a=trns[idx] if trns and idx<len(trns) else 255
                out.append((r,g,b,a))
    return w,h,out

def mean_chroma(px):
    vis=[p for p in px if p[3]>8]
    if not vis: return 0.0
    return sum((max(p[:3])-min(p[:3]))/255 for p in vis)/len(vis)
