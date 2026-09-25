"""Exercise the actual transport shader on synthetic textures in surfaceless EGL."""
import ctypes as C
import math
import os
from pathlib import Path
import re
import time
assert os.environ.get('QT_QPA_PLATFORM')=='offscreen'
assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
root=Path(__file__).resolve().parent
lib=C.CDLL(os.environ.get('GF_RENDERER_PATH',str(root/'renderer.so')))
assert lib.gf_headless(16,16),'Surfaceless EGL required; refusing fallback'
gl=C.CDLL('libGLESv2.so.2')
u=C.c_uint;i=C.c_int;f=C.c_float;p=C.c_void_p

def api(name,result,*args):
    fn=getattr(gl,'gl'+name);fn.restype=result;fn.argtypes=list(args);return fn
create=api('CreateShader',u,u); source=api('ShaderSource',None,u,i,C.POINTER(C.c_char_p),p)
compile_=api('CompileShader',None,u);get_shader=api('GetShaderiv',None,u,u,C.POINTER(i))
log=api('GetShaderInfoLog',None,u,i,p,C.c_char_p)
program=api('CreateProgram',u);attach=api('AttachShader',None,u,u);link=api('LinkProgram',None,u)
get_program=api('GetProgramiv',None,u,u,C.POINTER(i));use=api('UseProgram',None,u)
loc=api('GetUniformLocation',i,u,C.c_char_p);uni=api('Uniform1f',None,i,f)
uni2=api('Uniform2f',None,i,f,f);unii=api('Uniform1i',None,i,i)
gen=api('GenTextures',None,i,C.POINTER(u));bind=api('BindTexture',None,u,u)
active=api('ActiveTexture',None,u);param=api('TexParameteri',None,u,u,i)
tex=api('TexImage2D',None,u,i,i,i,i,i,u,u,p)
genfb=api('GenFramebuffers',None,i,C.POINTER(u));fb=api('BindFramebuffer',None,u,u)
attachtex=api('FramebufferTexture2D',None,u,u,u,u,i);status=api('CheckFramebufferStatus',u,u)
viewport=api('Viewport',None,i,i,i,i);draw=api('DrawArrays',None,u,i,i)
read=api('ReadPixels',None,i,i,i,i,u,u,p);finish=api('Finish',None)
error=api('GetError',u);getstr=api('GetString',C.c_char_p,u)
print('GPU:',getstr(0x1F01).decode(),flush=True)
text=(root/'renderer.cpp').read_text()
# Vertex positions match the renderer's fullscreen triangle.
vertex='''#version 300 es
out vec2 uv;
void main(){vec2 p=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2));uv=p;gl_Position=vec4(p*2.-1.,0.,1.);}'''
fragment=re.search(r'static const char \*warp_fs=R"GLSL\((.*?)\)GLSL"',text,re.S).group(1)
def build(fragment):
    prog=program()
    for kind,body in [(0x8B31,vertex),(0x8B30,fragment)]:
        sh=create(kind);src=C.c_char_p(body.encode());source(sh,1,C.byref(src),None);compile_(sh)
        ok=i();get_shader(sh,0x8B81,C.byref(ok))
        if not ok.value:
            msg=C.create_string_buffer(8192);log(sh,8192,None,msg);raise AssertionError(msg.value)
        attach(prog,sh)
    link(prog);ok=i();get_program(prog,0x8B82,C.byref(ok));assert ok.value
    return prog
programs={'linear':build(fragment.replace('carried(source)','texture(history,source).r')),'cubic':build(fragment)}
textures=(u*3)();gen(3,textures);frames=(u*2)();genfb(2,frames)
def run(method,values,w,h,dx,dy,count,persist=1.,fade=0.,step=1.,readback=True,sharpness=1.):
    for n in range(3):
        active(0x84C0);bind(0x0DE1,textures[n])
        for key,val in [(0x2801,0x2601),(0x2800,0x2601),(0x2802,0x812F),(0x2803,0x812F)]:param(0x0DE1,key,val)
        if n<2:
            data=(f*(w*h))(*values)
            tex(0x0DE1,0,0x822D,w,h,0,0x1903,0x1406,data)
            fb(0x8D40,frames[n]);attachtex(0x8D40,0x8CE0,0x0DE1,textures[n],0)
            assert status(0x8D40)==0x8CD5
        else:
            data=(f*(w*h*2))(*[v for y in range(h) for x in range(w) for v in ((x+.5+dx)/w,(y+.5+dy)/h)])
            tex(0x0DE1,0,0x8230,w,h,0,0x8227,0x1406,data)
    prog=programs[method];use(prog);viewport(0,0,w,h)
    for key,val in [('trailSharpness',sharpness),('persist',persist),('fadeBias',fade),('step',step),('flowStep',1.),('historyScale',1.)]:uni(loc(prog,key.encode()),val)
    uni2(loc(prog,b'grid'),w,h)
    unii(loc(prog,b'history'),0);unii(loc(prog,b'field'),1)
    active(0x84C1);bind(0x0DE1,textures[2]);current=0
    finish();start=time.monotonic()
    for _ in range(count):
        active(0x84C0);bind(0x0DE1,textures[current]);current=1-current;fb(0x8D40,frames[current]);draw(4,0,3)
    finish();duration=(time.monotonic()-start)/count
    if not readback:return duration
    result=(f*(w*h*4))();read(0,0,w,h,0x1908,0x1406,result)
    assert error()==0
    return list(result)[::4]
try:
    w=h=96
    for shift in [(0,0),(.25,.17),(-.3,.4),(2.3,-1.1)]:
        result=run('cubic',[.625]*(w*h),w,h,*shift,30)
        assert max(abs(v-.625) for v in result)<.002
    print('PASS: constant fields and reflected borders remain uniform')
    pattern=lambda x,y:.5+.35*math.sin(2*math.pi*x/12)*math.cos(2*math.pi*y/17)
    values=[pattern(x,y) for y in range(h) for x in range(w)]
    identity=run('cubic',values,w,h,0,0,60)
    assert max(abs(a-b) for a,b in zip(identity,values))<.001, (max(abs(a-b) for a,b in zip(identity,values)), identity[:12], values[:12])
    print('PASS: stationary history retains its detail')
    linear=run('linear',values,w,h,.25,.17,30)
    soft=run('cubic',values,w,h,.25,.17,30,sharpness=0.)
    middle=run('cubic',values,w,h,.25,.17,30,sharpness=.5)
    sharp=run('cubic',values,w,h,.25,.17,30,sharpness=1.)
    assert soft==linear,'0% must match linear sampling'
    contrast=lambda pixels:max(pixels)-min(pixels)
    assert contrast(soft)<contrast(middle)<contrast(sharp)
    print('PASS: sharpness dial endpoints and intermediate detail retention')
    for fps in (30,60,120):
        count=fps//2;dx=6/count;dy=3/count;errors={}
        for method in programs:
            result=run(method,values,w,h,dx,dy,count)
            errors[method]=math.sqrt(sum((result[y*w+x]-pattern(x+6,y+3))**2 for y in range(15,h-15) for x in range(15,w-15))/((w-30)*(h-30)))
        assert errors['cubic']<errors['linear']*.8,errors
        print(f'PASS: {fps} FPS smooth-detail RMS error: {errors}',flush=True)
    for pattern in [lambda x,y:float(x>y),lambda x,y:float(abs(x-45)<2),lambda x,y:float((x//4+y//4)%2)]:
        values=[.2+.6*pattern(x,y) for y in range(h) for x in range(w)]
        result=run('cubic',values,w,h,.25,.17,60)
        assert min(result)>=.198 and max(result)<=.802,(min(result),max(result))
    print('PASS: diagonal edges, thin lines, checkerboards gain no overshoot halos')
    result=run('cubic',[.625]*(w*h),w,h,.25,.17,30,.97,.002)
    expected=.625*.97**30-.002*(1-.97**30)/(1-.97)
    assert max(abs(v-expected) for v in result)<.004
    print('PASS: trail decay remains unchanged')
    for method in programs:
        ms=run(method,[.625]*(1920*1080),1920,1080,.25,.17,60,readback=False)*1000
        print(f'1080p transport {method}: {ms:.3f} ms/pass',flush=True)
finally:
    lib.gf_headless_close()
