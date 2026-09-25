#include <GLES3/gl3.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <random>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include "G-Force_Proj.h"
#include "G-Force.h"
#include "ParticleGroup.h"
#include "DeltaField.h"
#include "EgOSUtils.h"
#include "gpu_hooks.h"

// FFTW's stable single-precision C ABI; Fedora provides the runtime library.
extern "C" {
struct fftwf_plan_s;
typedef fftwf_plan_s* fftwf_plan;
fftwf_plan fftwf_plan_dft_r2c_1d(int, float*, float (*)[2], unsigned);
void fftwf_execute(const fftwf_plan);
void fftwf_destroy_plan(fftwf_plan);
}
struct AudioFFT {
    alignas(64) float input[550]{};
    alignas(64) float output[276][2]{};
    fftwf_plan plan = fftwf_plan_dft_r2c_1d(550, input, output, 64 /* ESTIMATE */);
    ~AudioFFT() { if (plan) fftwf_destroy_plan(plan); }
    void run(const float *pcm, float *spectrum) {
        std::memcpy(input, pcm, sizeof(input));
        fftwf_execute(plan);
        for (int k=0; k<180; k++) spectrum[k] = 3.f * std::hypot(output[k][0], output[k][1]) / 550.f;
    }
};
long gpu_load_seed_peek(char kind);
void gpu_load_seed_queue(char kind,long seed);
class DemoEngine : public GForce {
public:
    bool changesPaused=false;
    bool particlesEnabled=true;
    // The engine stores mParticlesOn as the P_On pref when it is destroyed.
    ~DemoEngine() { mParticlesOn=particlesEnabled; }
    void setParticles(bool on) {
        bool was=particlesEnabled;
        particlesEnabled=on; mParticlesOn=on&&!changesPaused;
        if (!on) clearParticles();
        if (mParticlesOn) mNextParticleCheck=mT+1;
        if (on && !was && mCurParticleNum>0) loadParticle(mCurParticleNum);
    }
    // Interval strings are compiled once by the engine; recompile and, unless
    // changes are paused, reschedule the next change from the new expression.
    void setInterval(char kind,const char *expr) {
        UtilStr str(expr);
        if (kind=='W') { mShapeIntervalStr.Assign(str); mShapeInterval.Compile(mShapeIntervalStr,mDict); if(!changesPaused) mNextShapeChange=mT+mShapeInterval.Evaluate(); }
        if (kind=='D') { mFieldIntervalStr.Assign(str); mFieldInterval.Compile(mFieldIntervalStr,mDict); if(!changesPaused) mNextFieldChange=mT+mFieldInterval.Evaluate(); }
        if (kind=='C') { mColorIntervalStr.Assign(str); mColorInterval.Compile(mColorIntervalStr,mDict); if(!changesPaused) mNextColorChange=mT+mColorInterval.Evaluate(); }
        if (kind=='P') { mParticleDuration.Assign(str); mParticleDurationFcn.Compile(mParticleDuration,mDict); }
        if (kind=='R') { mParticleProbability.Assign(str); mParticleProbabilityFcn.Compile(mParticleProbability,mDict); }
    }
    const char *interval(char kind) {
        switch (kind) {
            case 'W': return mShapeIntervalStr.getCStr();
            case 'D': return mFieldIntervalStr.getCStr();
            case 'C': return mColorIntervalStr.getCStr();
            case 'P': return mParticleDuration.getCStr();
            case 'R': return mParticleProbability.getCStr();
        }
        return "";
    }
    // "audio only": shapes and particles whose equations never call mag() or
    // fft() move the same with or without sound. Hiding them drops them from
    // the playlists the slideshow, W and R draw from; presets still recall them.
    bool audioOnly=false;
    XLongList allShapes, allParticles;
    std::vector<signed char> shapeReacts, particleReacts;
    static bool reactsToAudio(const CEgFileSpec *spec) {
        if (!spec) return true;
        std::ifstream in((const char*)spec->OSSpec());
        std::string s((std::istreambuf_iterator<char>(in)),std::istreambuf_iterator<char>());
        s=std::regex_replace(s,std::regex(R"(/\*[\s\S]*?\*/|//[^\n]*)"),"");
        return std::regex_search(s,std::regex(R"(\b(mag|fft)\s*\()",std::regex::icase));
    }
    static bool reacts(std::vector<signed char> &cache,FileSpecList &specs,long i) {
        if (cache.size()<=size_t(i)) cache.resize(i+1,-1);
        if (cache[i]<0) cache[i]=reactsToAudio(specs.FetchSpec(i));
        return cache[i];
    }
    void filter(XLongList &list,XLongList &all,std::vector<signed char> &cache,FileSpecList &specs) {
        if (all.Count()==0) all.Add(list);
        list.RemoveAll();
        for (long k=1; k<=all.Count(); k++)
            if (!audioOnly || reacts(cache,specs,all.Fetch(k))) list.Add(all.Fetch(k));
        if (list.Count()==0) list.Add(all);
        list.Randomize();
    }
    void setAudioOnly(bool on) {
        // Every dials.json reload re-applies this; only a real change reshuffles.
        if (on==audioOnly && allShapes.Count()) return;
        audioOnly=on;
        filter(mShapePlayList,allShapes,shapeReacts,mWaveShapes);
        filter(mParticlePlayList,allParticles,particleReacts,mParticles);
        if (!on) return;
        if (!reacts(shapeReacts,mWaveShapes,mCurShapeNum))
            loadWaveShape(mShapePlayList.Fetch(1),mShapeTransTime<=0);
        for (auto p=(ParticleGroup*)mRunningParticlePool.GetHead(); p; ) {
            auto next=(ParticleGroup*)p->GetNext();
            long i=mParticles.Lookup(p->mTitle);
            if (i>0 && !reacts(particleReacts,mParticles,i)) { mStoppedParticlePool.addToHead(p); mNumRunningParticles--; }
            p=next;
        }
    }
    void setSetting(const std::string &name,double v) {
        if (name=="sensitivity") mMagScale=v;
        else if (name=="audioOnly") setAudioOnly(v!=0);
        else if (name=="normalize") mNormalizeInput=v!=0;
        else if (name=="steps") SetNumSampleBins(std::clamp(long(v),16L,1000L));
        else if (name=="particles") setParticles(v!=0);
        else if (name=="transitionLo") mTransitionLo=std::max(0L,long(v));
        else if (name=="transitionHi") mTransitionHi=std::max(0L,long(v));
        else if (name=="paused") setPaused(v!=0);
        else throw std::runtime_error("unknown engine setting "+name);
    }
    double setting(const std::string &name) {
        if (name=="sensitivity") return mMagScale;
        if (name=="audioOnly") return audioOnly;
        if (name=="normalize") return mNormalizeInput;
        if (name=="steps") return mNum_S_Steps;
        if (name=="particles") return particlesEnabled;
        if (name=="transitionLo") return mTransitionLo;
        if (name=="transitionHi") return mTransitionHi;
        if (name=="paused") return changesPaused;
        throw std::runtime_error("unknown engine setting "+name);
    }
    void setPaused(bool paused) {
        changesPaused=paused;
        mFieldSlideShow=mColorSlideShow=mShapeSlideShow=!paused;
        mParticlesOn=particlesEnabled&&!paused;
        if (!paused) {
            mNextFieldChange=mT+mFieldInterval.Evaluate();
            mNextColorChange=mT+mColorInterval.Evaluate();
            mNextShapeChange=mT+mShapeInterval.Evaluate();
            mNextParticleCheck=mT+1;
        }
    }
    void randomize() {
        auto pick=[](XLongList& list, long current) {
            long n=list.Count();
            long index=1+rand()%n;
            if (n>1 && list.Fetch(index)==current) index=index%n+1;
            return list.Fetch(index);
        };
        long hi=mTransitionHi;
        mTransitionHi=mTransitionLo;
        if (mShapeTransTime>0) { std::swap(mWave,mNextWave); mShapeTransTime=-1; }
        if (mColorTransTime>0) { std::swap(mGF_Palette,mNextPal); mColorTransTime=-1; }
        loadWaveShape(pick(mShapePlayList,mCurShapeNum),true);
        loadColorMap(pick(mColorPlayList,mCurColorMapNum),true);
        mTransitionHi=hi;
        loadDeltaField(pick(mFieldPlayList,mCurFieldNum));
        // Replace particles rather than accumulating groups on repeated R.
        clearParticles();
        if (particlesEnabled) loadParticle(pick(mParticlePlayList,mCurParticleNum));
    }
    // Manual next: W wave shape, C distortion, X colours, as the menu names
    // them (the legacy key map binds W to colours and C to a slideshow
    // toggle). Shapes and colours blend over the short end of the blend range
    // instead of cutting; a change pressed mid-blend first lands the one in
    // progress. Distortions switch at once, as automatic ones do.
    void manualNext(char kind) {
        auto next=[](XLongList& list,long current) {
            return list.Fetch(1+list.FindIndexOf(current)%list.Count());
        };
        long hi=mTransitionHi;
        mTransitionHi=mTransitionLo;
        if (kind=='W') {
            if (mShapeTransTime>0) { std::swap(mWave,mNextWave); mShapeTransTime=-1; }
            loadWaveShape(next(mShapePlayList,mCurShapeNum),true);
        } else if (kind=='X') {
            if (mColorTransTime>0) { std::swap(mGF_Palette,mNextPal); mColorTransTime=-1; }
            loadColorMap(next(mColorPlayList,mCurColorMapNum),true);
        } else if (kind=='P') {
            long selected=next(mParticlePlayList,mCurParticleNum);
            setParticles(true);
            clearParticles();
            loadParticle(selected);
        } else if (kind=='C') {
            loadDeltaField(next(mFieldPlayList,mCurFieldNum));
        }
        mTransitionHi=hi;
    }
    FileSpecList* files(char kind) {
        switch(kind) {
            case 'W': return &mWaveShapes;
            case 'D': return &mDeltaFields;
            case 'C': return &mColorMaps;
            case 'P': return &mParticles;
        }
        return nullptr;
    }
    std::string choices(char kind) {
        std::ostringstream out;
        auto f=files(kind);
        if(f) for(long i=1;i<=f->Count();i++) {
            if(audioOnly && kind=='W' && !reacts(shapeReacts,*f,i)) continue;
            if(audioOnly && kind=='P' && !reacts(particleReacts,*f,i)) continue;
            UtilStr name; f->FetchSpecName(i,name); out<<name.getCStr()<<"\n";
        }
        return out.str();
    }
    std::string selection(char kind) {
        auto f=files(kind);
        if(!f) return "";
        long i=kind=='W'?mCurShapeNum:kind=='D'?mCurFieldNum:kind=='C'?mCurColorMapNum:mCurParticleNum;
        if(i<1 || i>f->Count()) return "";
        UtilStr name; f->FetchSpecName(i,name); return name.getCStr();
    }
    bool select(char kind,const char* name) {
        auto f=files(kind); UtilStr n(name);
        if(!f || f->Lookup(n)<=0) return false;
        if(kind=='P') { setParticles(true); clearParticles(); }
        if(kind=='W' && mShapeTransTime>0) { std::swap(mWave,mNextWave); mShapeTransTime=-1; }
        if(kind=='C' && mColorTransTime>0) { std::swap(mGF_Palette,mNextPal); mColorTransTime=-1; }
        long hi=mTransitionHi; mTransitionHi=mTransitionLo;
        // A selected field is loaded into shown/next slots; keep their seed
        // identical so saving this selection recalls the field being shown.
        if(kind=='D') gpu_load_seed_queue('D',gpu_load_seed('D'));
        bool ok=recall(kind,name,true);
        mTransitionHi=hi;
        return ok;
    }
    void state(long* values) {
        values[0]=changesPaused; values[1]=mCurShapeNum;
        values[2]=mCurFieldNum; values[3]=mCurColorMapNum;
        values[4]=mCurParticleNum; values[5]=mT_MS;
    }
    // Preset capture: one line per component, "kind<TAB>file name<TAB>seed".
    // The shape and colour lines name the latest load, i.e. the destination of
    // any morph in progress.
    std::string capture(const long seeds[3]) {
        std::ostringstream out;
        UtilStr field;
        mDeltaFields.FetchSpecName(mCurFieldNum,field);
        out<<"W\t"<<mWaveShapeName.getCStr()<<"\t"<<seeds[0]<<"\n";
        out<<"D\t"<<field.getCStr()<<"\t"<<seeds[1]<<"\n";
        out<<"C\t"<<mColorMapName.getCStr()<<"\t"<<seeds[2]<<"\n";
        for (auto p=(ParticleGroup*)mRunningParticlePool.GetHead(); p; p=(ParticleGroup*)p->GetNext())
            out<<"P\t"<<p->mTitle.getCStr()<<"\t"<<p->mSeed<<"\n";
        return out.str();
    }
    // Load one named component; the caller has queued its seed. With morph,
    // shapes and colours blend in like a manual change; without, they cut.
    bool recall(char kind,const char *name,bool morph) {
        UtilStr str(name);
        switch (kind) {
            case 'W': { long i=mWaveShapes.Lookup(str); if(i<=0) return false; loadWaveShape(i,morph); return true; }
            case 'D': {
                long i=mDeltaFields.Lookup(str); if(i<=0) return false;
                // mField is shown; mNextField is computed in the background for
                // the next change. Load the recalled field into both, so a field
                // queued by the previous look neither shows up next nor shares
                // the rnd() stream while it computes. Both take the same seed.
                long seed=gpu_load_seed_peek('D');
                loadDeltaField(i);
                std::swap(mField,mNextField);
                gpu_load_seed_queue('D',seed);
                loadDeltaField(i);
                std::swap(mField,mNextField);
                return true; }
            case 'C': { long i=mColorMaps.Lookup(str); if(i<=0) return false; loadColorMap(i,morph); return true; }
            case 'P': { long i=mParticles.Lookup(str); if(i<=0) return false; particlesEnabled=true; mParticlesOn=!changesPaused; loadParticle(i); return true; }
        }
        return false;
    }
    void clearParticles() {
        while (auto particle=mRunningParticlePool.GetHead())
            mStoppedParticlePool.addToHead(particle);
        mNumRunningParticles=0;
    }
    DemoEngine() { mT_MS_Base=0; mConsoleExpireTime=0; mTrackTextPosMode=0; particlesEnabled=mParticlesOn; }
    void remapFields(int w,int h) {
        mField1.SetSize(w,h,mPortA.GetRowSize(),true);
        mField2.SetSize(w,h,mPortA.GetRowSize(),true);
    }
    void resize(int w, int h) {
        Rect r={0,0,(short)w,(short)h}; SetWinPort(nullptr,&r); StoreWinRect();
    }
};
struct Segment { float sx,sy,ex,ey,a,b,width; };
static const char *quad_vs=R"GLSL(#version 300 es
precision highp float;
out vec2 uv;
void main() {
    vec2 p=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2));
    uv=p; gl_Position=vec4(p*2.-1.,0.,1.);
})GLSL";
static const char *warp_fs=R"GLSL(#version 300 es
precision highp float;
// Sampler precision must retain subpixel field coordinates and history values.
uniform highp sampler2D history;
uniform highp sampler2D field;
uniform vec2 grid;
uniform float persist;
uniform float fadeBias;
uniform float trailSharpness;
// Frames are 1/30 s in the original; step scales one frame's motion, so the
// flow and the trail decay keep their speed at any frame rate.
uniform float step;
uniform float flowStep;
uniform float historyScale;
in vec2 uv;
layout(location=0) out vec4 colour;
vec4 cubicWeights(float t) {
    float t2=t*t, t3=t2*t;
    return vec4(-.5*t+t2-.5*t3, 1.-2.5*t2+1.5*t3,
                .5*t+2.*t2-1.5*t3, -.5*t2+.5*t3);
}
float carried(vec2 at) {
    ivec2 size=textureSize(history,0);
    vec2 p=at*vec2(size)-.5;
    // Preserve exact texel centres despite normalized-coordinate roundoff.
    vec2 centre=round(p);
    p=mix(p,centre,lessThan(abs(p-centre),vec2(.0001)));
    ivec2 base=ivec2(floor(p));
    vec4 wx=cubicWeights(fract(p.x)), wy=cubicWeights(fract(p.y));
    float value=0., lo=1., hi=0.;
    for(int y=0;y<4;y++) for(int x=0;x<4;x++) {
        float v=texelFetch(history,clamp(base+ivec2(x-1,y-1),ivec2(0),size-1),0).r;
        value+=v*wx[x]*wy[y];
        if(x>=1 && x<=2 && y>=1 && y<=2) { lo=min(lo,v); hi=max(hi,v); }
    }
    // Cubic reconstruction limits repeated transport blur. Bound it by the
    // central source samples so negative lobes cannot grow bright/dark halos.
    return clamp(value,lo,hi);
}
void main() {
    vec2 p=uv*grid-.5;
    ivec2 i=ivec2(floor(p)); vec2 f=fract(p);
    ivec2 hi=ivec2(grid)-1;
    vec2 a=texelFetch(field,clamp(i,ivec2(0),hi),0).rg;
    vec2 b=texelFetch(field,clamp(i+ivec2(1,0),ivec2(0),hi),0).rg;
    vec2 c=texelFetch(field,clamp(i+ivec2(0,1),ivec2(0),hi),0).rg;
    vec2 d=texelFetch(field,clamp(i+ivec2(1,1),ivec2(0),hi),0).rg;
    vec2 pos=mix(mix(a,b,f.x),mix(c,d,f.x),f.y);
    float decay=pow(persist,step);
    // Zoom the carried image once when scene scale changes; the mapping
    // still covers every output pixel, including while master speed is zero.
    vec2 source=uv+(pos-uv)*flowStep;
    source=.5+(source-.5)/historyScale;
    // Reflect out-of-frame samples instead of turning them black or
    // stretching a single border texel into a stripe.
    source=1.-abs(1.-mod(source,2.));
    float sampleValue=texture(history,source).r;
    if(trailSharpness>0.) sampleValue=mix(sampleValue,carried(source),trailSharpness);
    float value=sampleValue*decay;
    // Fractional iterations of value = persist * value - fadeBias.
    // This preserves the fade-to-black time as well as exponential half-life.
    float fadeSteps=persist<.99999 ? (1.-decay)/(1.-persist) : step;
    value=max(0.,value-fadeBias*fadeSteps);
    colour=vec4(value,0.,0.,1.);
})GLSL";
static const char *present_fs=R"GLSL(#version 300 es
precision highp float;
uniform highp sampler2D history;
uniform sampler2D palette;
uniform vec2 outputPixel;
uniform float supersample;
in vec2 uv;
out vec4 colour;
vec3 mapped(vec2 at) {
    float value=clamp(texture(history,at).r,0.,1.);
    return texture(palette,vec2((value*255.+.5)/256.,.5)).rgb;
}
void main() {
    vec2 at=vec2(uv.x,1.-uv.y);
    vec3 rgb;
    if(supersample>1.) {
        vec2 d=outputPixel*.25;
        rgb=(mapped(at+d)+mapped(at-d)+mapped(at+vec2(d.x,-d.y))+mapped(at+vec2(-d.x,d.y)))*.25;
    } else rgb=mapped(at);
    colour=vec4(rgb,1.);
})GLSL";
static const char *line_vs=R"GLSL(#version 300 es
precision highp float;
layout(location=0) in vec4 endpoints;
layout(location=1) in vec3 values;
uniform vec2 grid;
uniform vec2 outputSize;
uniform float widthScale;
uniform float minRadius;
uniform float softness;
out vec2 local;
flat out float lineLength;
flat out float radius;
flat out vec2 intensities;
void main() {
    vec2 scale=outputSize/grid;
    vec2 a=(endpoints.xy+.5)*scale;
    vec2 b=(endpoints.zw+.5)*scale;
    vec2 delta=b-a;
    lineLength=length(delta);
    vec2 dir=lineLength>0.0001?delta/lineLength:vec2(1.,0.);
    vec2 normal=vec2(-dir.y,dir.x);
    radius=max(minRadius,values.z*widthScale*.5*min(scale.x,scale.y));
    float pad=max(1.,softness);
    vec2 corners[6]=vec2[6](vec2(0.,-1.),vec2(1.,-1.),vec2(0.,1.),vec2(0.,1.),vec2(1.,-1.),vec2(1.,1.));
    vec2 c=corners[gl_VertexID];
    local=vec2(mix(-radius-pad,lineLength+radius+pad,c.x),c.y*(radius+pad));
    vec2 p=a+dir*local.x+normal*local.y;
    gl_Position=vec4(p/outputSize*2.-1.,0.,1.);
    intensities=values.xy;
})GLSL";
static const char *line_fs=R"GLSL(#version 300 es
precision highp float;
in vec2 local;
flat in float lineLength;
flat in float radius;
flat in vec2 intensities;
uniform float softness;
out vec4 colour;
void main() {
    float x=clamp(local.x,0.,lineLength);
    float dist=length(vec2(local.x-x,local.y));
    float coverage=clamp((radius-dist)/softness+.5,0.,1.);
    if(coverage<=0.) discard;
    float value=mix(intensities.x,intensities.y,lineLength>0.0001?x/lineLength:0.);
    colour=vec4(clamp(value,0.,1.),0.,0.,coverage);
})GLSL";

static GLuint compile(GLenum kind,const char *source) {
    GLuint s=glCreateShader(kind); glShaderSource(s,1,&source,nullptr); glCompileShader(s);
    GLint ok; glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
    if(!ok) { char log[4096]; glGetShaderInfoLog(s,sizeof(log),nullptr,log); glDeleteShader(s); throw std::runtime_error(log); }
    return s;
}
static GLuint program(const char *vs,const char *fs) {
    GLuint v=compile(GL_VERTEX_SHADER,vs),f=compile(GL_FRAGMENT_SHADER,fs),p=glCreateProgram();
    glAttachShader(p,v); glAttachShader(p,f); glLinkProgram(p); glDeleteShader(v); glDeleteShader(f);
    GLint ok; glGetProgramiv(p,GL_LINK_STATUS,&ok);
    if(!ok) { char log[4096]; glGetProgramInfoLog(p,sizeof(log),nullptr,log); throw std::runtime_error(log); }
    return p;
}
static void bindtex(GLuint prog,const char *name,GLuint tex,int unit) {
    glActiveTexture(GL_TEXTURE0+unit); glBindTexture(GL_TEXTURE_2D,tex);
    glUniform1i(glGetUniformLocation(prog,name),unit);
}
static void texture_params(GLint filter) {
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,filter);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,filter);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
}
struct Renderer {
    AudioFFT fft;
    DemoEngine *engine=nullptr;
    GLuint warp=0,present=0,line=0,quadVao=0,lineVao=0,vbo=0;
    GLuint history[2]{},fbo[2]{},field=0,palette=0;
    int width=0,height=0,outputWidth=0,outputHeight=0,gw=640,gh=480,current=0;
    float resolution=1.f,distortionScale=1.f,waveScale=1.f,particleScale=1.f,historyScale=1.f;
    bool particleLayer=false;
    double waveLength=0.,particleLength=0.;
    double masterSpeed=1.,waveSpeed=1.,particleSpeed=1.,colourSpeed=1.,flowSpeed=1.;
    double engineMs=0.,waveMs=0.,particleMs=0.,colourMs=0.;
    float waveTime=0.f,particleTime=0.f,colourTime=0.f,waveSmoothing=1.3f;
    // Live dials. Defaults reproduce the original constants.
    float trailSharpness=1.f;
    int trailFill=1;
    bool forceConnect=false;
    bool forcePoints=false;
    float waveResponse=0.f;
    std::vector<size_t> waveIndices;
    std::vector<Segment> previousWave;
    std::string previousWaveName;
    int previousWaveGridW=0,previousWaveGridH=0;
    float persist=31.f/32.f,fadeBias=.5f/255.f,widthScale=1.f,minRadius=.5f,softness=1.f;
    int gridCap=640;
    float fps=30.f;   // requested presentation rate; never a simulation clock
    long lastMs=-1;
    double elapsedSteps=0.;   // diagnostic: integrated original 30 Hz frame units
    long frameSeed=0,frameCount=0;   // test hook: reseed rand() every frame
    bool drawLines=true;             // test hook: warp existing trails only
    // Load seeds: the last one used per kind (W, D, C), queued ones for a recall.
    std::mt19937 seeds{std::random_device{}()};
    long lastSeed[3]{};
    std::vector<std::pair<char,long>> queued;
    const void* fieldIdentity=nullptr;
    uint64_t fieldRevision=0;
    // Opt-in invariant check for isolated tests; normal rendering keeps no copy.
    bool verifyField=std::getenv("GF_VERIFY_FIELD")!=nullptr;
    std::vector<float> verifyFieldCopy;
    bool fieldAllocated=false;
    std::vector<Segment> segments;
    float spectrum[180]{},samples[550]{};
    bool capturing=false;
    void init() {
        if(!fft.plan) throw std::runtime_error("FFTW plan creation failed");
        const char *renderer=(const char*)glGetString(GL_RENDERER);
        if(!renderer) throw std::runtime_error("No current GL context");
        fprintf(stderr,"GL renderer: %s\n",renderer);
        warp=program(quad_vs,warp_fs); present=program(quad_vs,present_fs); line=program(line_vs,line_fs);
        glGenVertexArrays(1,&quadVao); glGenVertexArrays(1,&lineVao); glGenBuffers(1,&vbo);
        glBindVertexArray(lineVao); glBindBuffer(GL_ARRAY_BUFFER,vbo);
        glEnableVertexAttribArray(0); glVertexAttribPointer(0,4,GL_FLOAT,GL_FALSE,sizeof(Segment),(void*)0); glVertexAttribDivisor(0,1);
        glEnableVertexAttribArray(1); glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,sizeof(Segment),(void*)(4*sizeof(float))); glVertexAttribDivisor(1,1);
        glGenTextures(2,history); glGenFramebuffers(2,fbo); glGenTextures(1,&field); glGenTextures(1,&palette);
        glBindTexture(GL_TEXTURE_2D,field); texture_params(GL_NEAREST);
        glBindTexture(GL_TEXTURE_2D,palette); texture_params(GL_LINEAR);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,256,1,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
        EgOSUtils::Initialize(nullptr); ScreenDevice::sMinDepth=8;
        engine=new DemoEngine;
        segments.reserve(16384);
    }
    void resize(int w,int h) {
        GLint limit; glGetIntegerv(GL_MAX_TEXTURE_SIZE,&limit);
        if(w<1||h<1||w>limit||h>limit) throw std::runtime_error("Render size outside GPU limits");
        double scale=std::min({double(resolution),double(limit)/w,double(limit)/h,
                               std::sqrt(33554432./(double(w)*h))});
        int rw=std::max(1,int(std::lround(w*scale))),rh=std::max(1,int(std::lround(h*scale)));
        outputWidth=w; outputHeight=h;
        if(rw==width&&rh==height) return;
        GLuint textures[2]{},buffers[2]{};
        glGenTextures(2,textures); glGenFramebuffers(2,buffers);
        try {
            for(int i=0;i<2;i++) {
                glBindTexture(GL_TEXTURE_2D,textures[i]); texture_params(GL_LINEAR);
                glTexImage2D(GL_TEXTURE_2D,0,GL_R16F,rw,rh,0,GL_RED,GL_HALF_FLOAT,nullptr);
                glBindFramebuffer(GL_FRAMEBUFFER,buffers[i]);
                glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,textures[i],0);
                if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)
                    throw std::runtime_error("R16F framebuffer allocation failed");
                if(width && height) {
                    glBindFramebuffer(GL_READ_FRAMEBUFFER,fbo[current]);
                    glBlitFramebuffer(0,0,width,height,0,0,rw,rh,GL_COLOR_BUFFER_BIT,GL_LINEAR);
                } else {
                    glViewport(0,0,rw,rh); glClearColor(0,0,0,0); glClear(GL_COLOR_BUFFER_BIT);
                }
            }
        } catch(...) {
            glDeleteTextures(2,textures); glDeleteFramebuffers(2,buffers); throw;
        }
        glDeleteTextures(2,history); glDeleteFramebuffers(2,fbo);
        std::copy(textures,textures+2,history); std::copy(buffers,buffers+2,fbo);
        width=rw; height=rh; current=0;
        resize_grid();
        fprintf(stderr,"Render %dx%d; output %dx%d; field grid %dx%d\n",width,height,w,h,gw,gh);
    }
    void resize_grid() {
        // Equation evaluation is independent of display pixels; keep its
        // detail cap bounded so resizing/supersampling do not inflate CPU work.
        int cap=std::clamp(gridCap,128,2048);
        int ngw=width>=height?cap:std::max(32,(cap*width/height)/4*4);
        int ngh=height>=width?cap:std::max(32,(cap*height/width)/4*4);
        if(ngw==gw&&ngh==gh&&fieldAllocated) return;
        gw=ngw; gh=ngh;
        engine->resize(gw,gh);
        fieldIdentity=nullptr;
        fieldAllocated=true;
        glBindTexture(GL_TEXTURE_2D,field);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RG32F,gw,gh,0,GL_RG,GL_FLOAT,nullptr);
    }
    void set_grid(int cap) {
        gridCap=std::clamp(cap,128,2048);
        resize_grid();
        fprintf(stderr,"Field grid %dx%d\n",gw,gh);
    }
    void set_distortion_scale(float value) {
        if(distortionScale==value) return;
        distortionScale=value;
        engine->remapFields(gw,gh);
        fieldIdentity=nullptr;
    }
    // Compatibility for archived callers. The UI migrates saved sceneScale
    // into three independent settings and no longer calls this combined dial.
    void set_scene_scale(float value) {
        historyScale*=value/distortionScale;
        waveScale=particleScale=value;
        set_distortion_scale(value);
    }
    void upload_field(int w,int h,const float *uv,const void* identity,uint64_t revision) {
        if(verifyField) {
            size_t size=size_t(w)*h*2;
            if(fieldIdentity==identity && fieldRevision==revision &&
               (verifyFieldCopy.size()!=size || std::memcmp(verifyFieldCopy.data(),uv,size*sizeof(float))!=0))
                throw std::runtime_error("field revision missed content change");
            verifyFieldCopy.assign(uv,uv+size);
        }
        // The engine alternates two field objects; revisions are local to each.
        if(fieldIdentity==identity && fieldRevision==revision) return;
        fieldIdentity=identity;
        fieldRevision=revision;
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,field);
        glTexSubImage2D(GL_TEXTURE_2D,0,0,0,w,h,GL_RG,GL_FLOAT,uv);
    }
    void ease_wave(double dt) {
        std::string name=engine->selection('W');
        bool continuous=previousWave.size()==waveIndices.size() && name==previousWaveName
            && previousWaveGridW==gw && previousWaveGridH==gh && dt<=250.;
        // The dial is approximate 95% settling time in real milliseconds.
        // Smooth drawn endpoints, leaving audio analysis and particles intact.
        float alpha=waveResponse>0.f && continuous ? float(-std::expm1(-3.*dt/waveResponse)) : 1.f;
        previousWave.resize(waveIndices.size());
        for(size_t i=0;i<waveIndices.size();i++) {
            auto &s=segments[waveIndices[i]]; const auto &p=previousWave[i];
            if(alpha<1.f) {
                s.sx=p.sx+(s.sx-p.sx)*alpha; s.sy=p.sy+(s.sy-p.sy)*alpha;
                s.ex=p.ex+(s.ex-p.ex)*alpha; s.ey=p.ey+(s.ey-p.ey)*alpha;
            }
            previousWave[i]=s;
        }
        previousWaveName=name; previousWaveGridW=gw; previousWaveGridH=gh;
    }
    void prepare_lines() {
        if(drawLines && !segments.empty()) {
            glUseProgram(line); glBindVertexArray(lineVao); glBindBuffer(GL_ARRAY_BUFFER,vbo);
            glBufferData(GL_ARRAY_BUFFER,segments.size()*sizeof(Segment),segments.data(),GL_STREAM_DRAW);
            glUniform2f(glGetUniformLocation(line,"grid"),gw,gh);
            glUniform2f(glGetUniformLocation(line,"outputSize"),width,height);
            glUniform1f(glGetUniformLocation(line,"widthScale"),widthScale);
            glUniform1f(glGetUniformLocation(line,"minRadius"),minRadius*float(width)/outputWidth);
            glUniform1f(glGetUniformLocation(line,"softness"),softness*float(width)/outputWidth);
        }
    }
    void stamp_lines() {
        glBindFramebuffer(GL_FRAMEBUFFER,fbo[current]);
        if(drawLines && !segments.empty()) {
            glUseProgram(line); glBindVertexArray(lineVao);
            glEnable(GL_BLEND); glBlendEquation(GL_FUNC_ADD); glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
            glDrawArraysInstanced(GL_TRIANGLES,0,6,segments.size()); glDisable(GL_BLEND);
        }
    }
    void draw(const float *pcm,long ms,GLuint target) {
        // The caller supplies monotonic elapsed milliseconds. Timer targets,
        // vsync, dropped frames and extra paints cannot change simulation speed.
        double dt=lastMs<0 ? std::max(0.,double(ms)) : std::max(0.,double(ms)-double(lastMs));
        double step=(lastMs<0 ? 1. : dt*.03)*masterSpeed;
        lastMs=std::max(lastMs,ms);
        engineMs+=dt*masterSpeed;
        waveMs+=dt*masterSpeed*waveSpeed;
        particleMs+=dt*masterSpeed*particleSpeed;
        colourMs+=dt*masterSpeed*colourSpeed;
        waveTime=waveMs*.001; particleTime=particleMs*.001; colourTime=colourMs*.001;
        elapsedSteps+=step;
        fft.run(pcm,spectrum);
        for(int i=0;i<550;i++) samples[i]=pcm[i]*32768.f;
        if(frameSeed) srand(unsigned(frameSeed+frameCount++));
        segments.clear(); waveIndices.clear(); waveLength=particleLength=0.; capturing=true;
        engine->RecordSample(std::lround(engineMs),samples,.000043f,550,spectrum,1,180);
        capturing=false;
        ease_wave(dt);
        glDisable(GL_DEPTH_TEST); glDisable(GL_SCISSOR_TEST); glDisable(GL_CULL_FACE); glDisable(GL_BLEND);
        glViewport(0,0,width,height);
        prepare_lines();
        // Subdivide long frame gaps so a low FPS does not take one oversized
        // displacement through a nonlinear field. Bound work after suspension.
        int passes=std::clamp(int(std::ceil(std::min(step*std::max(1.,flowSpeed),120.))),1,120);
        // Deposit the current wave between smaller transport steps. The engine
        // still evaluates once per real frame; extra impressions cannot advance
        // preset equations, random streams or particle lifetimes.
        int impressions=(step>0. && drawLines && !segments.empty())?trailFill:1;
        passes=std::max(passes,impressions);
        for(int pass=0;pass<passes;pass++) {
            if(step>0. || historyScale!=1.f) {
                int next=1-current;
                glBindFramebuffer(GL_FRAMEBUFFER,fbo[next]); glBindVertexArray(quadVao); glUseProgram(warp);
                bindtex(warp,"history",history[current],0); bindtex(warp,"field",field,1);
                glUniform2f(glGetUniformLocation(warp,"grid"),gw,gh);
                glUniform1f(glGetUniformLocation(warp,"persist"),persist);
                glUniform1f(glGetUniformLocation(warp,"fadeBias"),fadeBias);
                glUniform1f(glGetUniformLocation(warp,"trailSharpness"),trailSharpness);
                glUniform1f(glGetUniformLocation(warp,"step"),float(step/passes));
                glUniform1f(glGetUniformLocation(warp,"flowStep"),float(step*flowSpeed/passes));
                glUniform1f(glGetUniformLocation(warp,"historyScale"),historyScale);
                glDrawArrays(GL_TRIANGLES,0,3);
                current=next;
                historyScale=1.f;
            }
            if((pass+1)*impressions/passes!=pass*impressions/passes) stamp_lines();
        }
        std::array<unsigned char,1024> colours;
        PixPalEntry *p=engine->GetPalette();
        for(int i=0;i<256;i++) { colours[i*4]=p[i].red; colours[i*4+1]=p[i].green; colours[i*4+2]=p[i].blue; colours[i*4+3]=255; }
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,palette);
        glTexSubImage2D(GL_TEXTURE_2D,0,0,0,256,1,GL_RGBA,GL_UNSIGNED_BYTE,colours.data());
        glViewport(0,0,outputWidth,outputHeight);
        glBindFramebuffer(GL_FRAMEBUFFER,target); glBindVertexArray(quadVao); glUseProgram(present);
        bindtex(present,"history",history[current],0); bindtex(present,"palette",palette,1);
        glUniform2f(glGetUniformLocation(present,"outputPixel"),1.f/outputWidth,1.f/outputHeight);
        glUniform1f(glGetUniformLocation(present,"supersample"),float(width)/outputWidth);
        glDrawArrays(GL_TRIANGLES,0,3);
        glBindVertexArray(0); glUseProgram(0);
        GLenum error=glGetError();
        if(error!=GL_NO_ERROR) throw std::runtime_error("GL error "+std::to_string(error));
    }
    ~Renderer() {
        capturing=false; delete engine;
        glDeleteTextures(2,history); glDeleteTextures(1,&field); glDeleteTextures(1,&palette);
        glDeleteFramebuffers(2,fbo); glDeleteBuffers(1,&vbo);
        glDeleteVertexArrays(1,&quadVao); glDeleteVertexArrays(1,&lineVao);
        glDeleteProgram(warp); glDeleteProgram(line); glDeleteProgram(present);
    }
};
static Renderer *active=nullptr;
static std::string error;
float gpu_scene_scale() { return active?active->distortionScale:1.f; }
void gpu_particle_layer(bool particles) { if(active) active->particleLayer=particles; }
void gpu_capture_field(int w,int h,const float* uv,const void* identity,uint64_t revision) {
    if(active && active->capturing) active->upload_field(w,h,uv,identity,revision);
}
float* gpu_clock(char kind,float* fallback) {
    if(!active) return fallback;
    return kind=='W'?&active->waveTime:kind=='P'?&active->particleTime:&active->colourTime;
}
bool gpu_smooth_wave(float* samples,int count) {
    if(!active) return false;
    double sigma=active->waveSmoothing;
    if(sigma<=0. || count<=0) return true;
    // The legacy Gaussian has a 40-entry static mask; the exposed control
    // needs a bounded wider kernel without that mask's overflow at sigma 5.
    int radius=std::min(48,int(std::ceil(4*sigma)));
    std::array<double,97> weights{};
    double sum=0.;
    for(int j=-radius;j<=radius;j++) sum+=(weights[j+radius]=std::exp(-.5*j*j/(sigma*sigma)));
    std::vector<float> source(samples,samples+count);
    for(int i=0;i<count;i++) {
        double value=0.;
        for(int j=-radius;j<=radius;j++) value+=weights[j+radius]*source[std::clamp(i+j,0,count-1)];
        samples[i]=value/sum;
    }
    return true;
}
bool gpu_active() { return active!=nullptr; }
bool gpu_force_connect() { return active && active->forceConnect; }
long gpu_forced_points() { return active && active->forcePoints ? long(active->engine->setting("steps")) : 0; }
bool gpu_capture_line(float sx,float sy,float ex,float ey,float a,float b,float width) {
    if(!active||!active->capturing) return false;
    // Transform each layer before drawing; the shared trail history and
    // full-window distortion field are not resized when only a wave changes.
    float scale=active->particleLayer?active->particleScale:active->waveScale;
    float cx=active->gw*.5f-.5f,cy=active->gh*.5f-.5f;
    sx=cx+(sx-cx)*scale; ex=cx+(ex-cx)*scale;
    sy=cy+(sy-cy)*scale; ey=cy+(ey-cy)*scale;
    width*=scale;
    if(active->segments.size()<200000 && std::isfinite(sx)&&std::isfinite(sy)&&std::isfinite(ex)&&std::isfinite(ey)
        &&std::abs(sx)<1e7&&std::abs(sy)<1e7&&std::abs(ex)<1e7&&std::abs(ey)<1e7)
    {
        if(!active->particleLayer) active->waveIndices.push_back(active->segments.size());
        active->segments.push_back({sx,sy,ex,ey,a,b,width});
        (active->particleLayer?active->particleLength:active->waveLength)+=std::hypot(ex-sx,ey-sy);
    }
    return true;
}
bool gpu_capture_fade(int w,int h,const uint32_t *field) {
    if(!active||!active->capturing) return false;
    // DeltaField::GetField already uploaded full floating-point coordinates.
    return true;
}
long gpu_load_seed_peek(char kind) {
    for(auto &q:active->queued) if(q.first==kind) return q.second;
    return -1;
}
void gpu_load_seed_queue(char kind,long seed) { if(seed>=0) active->queued.push_back({kind,seed}); }
long gpu_load_seed(char kind) {
    if(!active) return rand();
    auto &r=*active;
    long seed=-1;
    for(auto it=r.queued.begin(); it!=r.queued.end(); ++it)
        if(it->first==kind) { seed=it->second; r.queued.erase(it); break; }
    if(seed<0) seed=long(r.seeds()&0x7fffffff);
    if(kind=='W') r.lastSeed[0]=seed; else if(kind=='D') r.lastSeed[1]=seed; else if(kind=='C') r.lastSeed[2]=seed;
    return seed;
}
extern "C" const char *gf_error() { return error.c_str(); }
extern "C" int gf_init(int w,int h) {
    try { active=new Renderer; active->init(); active->resize(w,h); return 1; }
    catch(const std::exception &e) { error=e.what(); delete active; active=nullptr; return 0; }
}
extern "C" int gf_resize(int w,int h) {
    try { active->resize(w,h); return 1; } catch(const std::exception &e) { error=e.what(); return 0; }
}
extern "C" int gf_frame(const float *pcm,long ms,unsigned fbo) {
    try { active->draw(pcm,ms,fbo); return 1; } catch(const std::exception &e) { error=e.what(); return 0; }
}
extern "C" void gf_key(int key) {
    if (!active) return;
    auto& engine=*active->engine;
    if (key=='r' || key=='R') engine.randomize();
    else if (strchr("wWcCxX",key)) engine.manualNext(char(toupper(key)));
    else if (key=='n' || key=='N') engine.manualNext('P');
    else if (key=='p' || key=='P') engine.setParticles(!engine.particlesEnabled);
    else if (key==' ') engine.setPaused(!engine.changesPaused);
    else {
        engine.HandleKey(key);
        // Legacy manual controls disable individual slideshows. Keep the
        // demo's single pause state authoritative after those controls.
        engine.setPaused(engine.changesPaused);
    }
}
// Dials: render names are applied on the next frame; "grid" re-maps the field
// in place (needs the GL context current); the rest go to the engine.
extern "C" int gf_set(const char *name,double v) {
    if(!active) return 0;
    try {
        if(!std::isfinite(v)) throw std::runtime_error("non-finite dial value");
        std::string n(name); auto &r=*active;
        if(n=="persist") r.persist=std::clamp(float(v),0.f,1.f);
        else if(n=="forceConnect") r.forceConnect=v!=0;
        else if(n=="forcePoints") r.forcePoints=v!=0;
        else if(n=="waveResponse") r.waveResponse=std::clamp(float(v),0.f,250.f);
        else if(n=="trailFill") r.trailFill=int(std::lround(std::clamp(v,1.,8.)));
        else if(n=="trailSharpness") r.trailSharpness=std::clamp(float(v),0.f,1.f);
        else if(n=="fadeBias") r.fadeBias=std::clamp(float(v),0.f,.1f);
        else if(n=="widthScale") r.widthScale=std::clamp(float(v),.05f,10.f);
        else if(n=="minWidth") r.minRadius=std::clamp(float(v),.5f,20.f)*.5f;
        else if(n=="softness") r.softness=std::clamp(float(v),.25f,8.f);
        else if(n=="grid") r.set_grid(int(v));
        else if(n=="masterSpeed") r.masterSpeed=std::clamp(v,0.,4.);
        else if(n=="waveSpeed") r.waveSpeed=std::clamp(v,0.,4.);
        else if(n=="particleSpeed") r.particleSpeed=std::clamp(v,0.,4.);
        else if(n=="colourSpeed") r.colourSpeed=std::clamp(v,0.,4.);
        else if(n=="flowSpeed") r.flowSpeed=std::clamp(v,0.,4.);
        else if(n=="waveSmoothing") r.waveSmoothing=std::clamp(float(v),0.f,12.f);
        else if(n=="waveScale") r.waveScale=std::clamp(float(v),.25f,3.f);
        else if(n=="particleScale") r.particleScale=std::clamp(float(v),.25f,3.f);
        else if(n=="distortionScale") r.set_distortion_scale(std::clamp(float(v),.25f,3.f));
        else if(n=="sceneScale") r.set_scene_scale(std::clamp(float(v),.25f,3.f));
        else if(n=="resolution") { r.resolution=std::clamp(float(v),.5f,2.f); r.resize(r.outputWidth,r.outputHeight); }
        else if(n=="fps") r.fps=std::clamp(float(v),5.f,240.f);
        else if(n=="drawLines") r.drawLines=v!=0;
        else if(n=="frameSeed") { r.frameSeed=long(v); r.frameCount=0; }
        else r.engine->setSetting(n,v);
        return 1;
    } catch(const std::exception &e) { error=e.what(); return 0; }
}
extern "C" double gf_get(const char *name) {
    if(!active) return 0;
    std::string n(name); auto &r=*active;
    if(n=="persist") return r.persist;
    if(n=="forceConnect") return r.forceConnect;
    if(n=="forcePoints") return r.forcePoints;
    if(n=="waveSegments") return r.waveIndices.size();
    if(n=="particleSegments") return r.segments.size()-r.waveIndices.size();
    if(n=="waveResponse") return r.waveResponse;
    if(n=="trailFill") return r.trailFill;
    if(n=="trailSharpness") return r.trailSharpness;
    if(n=="fadeBias") return r.fadeBias;
    if(n=="widthScale") return r.widthScale;
    if(n=="minWidth") return r.minRadius*2;
    if(n=="softness") return r.softness;
    if(n=="grid") return r.gridCap;
    if(n=="lineLength") {
        double length=0.;
        for(const auto& line:r.segments) length+=std::hypot(line.ex-line.sx,line.ey-line.sy);
        return length;
    }
    if(n=="masterSpeed") return r.masterSpeed;
    if(n=="waveSpeed") return r.waveSpeed;
    if(n=="particleSpeed") return r.particleSpeed;
    if(n=="colourSpeed") return r.colourSpeed;
    if(n=="flowSpeed") return r.flowSpeed;
    if(n=="waveSmoothing") return r.waveSmoothing;
    if(n=="waveScale") return r.waveScale;
    if(n=="particleScale") return r.particleScale;
    if(n=="distortionScale" || n=="sceneScale") return r.distortionScale;
    if(n=="fieldWidth") return r.gw;
    if(n=="fieldHeight") return r.gh;
    if(n=="waveLength") return r.waveLength;
    if(n=="particleLength") return r.particleLength;
    if(n=="resolution") return r.resolution;
    if(n=="renderWidth") return r.width;
    if(n=="renderHeight") return r.height;
    if(n=="waveTime") return r.waveTime;
    if(n=="particleTime") return r.particleTime;
    if(n=="colourTime") return r.colourTime;
    if(n=="fps") return r.fps;
    if(n=="elapsedSteps") return r.elapsedSteps;
    try { return r.engine->setting(n); } catch(const std::exception &e) { error=e.what(); return 0; }
}
extern "C" const char *gf_choices(int kind) {
    static std::string text; text=active?active->engine->choices(char(kind)):""; return text.c_str();
}
extern "C" const char *gf_selection(int kind) {
    static std::string text; text=active?active->engine->selection(char(kind)):""; return text.c_str();
}
extern "C" int gf_select(int kind,const char* name) {
    if(!active) return 0;
    return active->engine->select(char(kind),name);
}
extern "C" const char *gf_get_interval(int kind) { return active?active->engine->interval(char(kind)):""; }
extern "C" void gf_set_interval(int kind,const char *expr) { if(active) active->engine->setInterval(char(kind),expr); }
static std::string presetText;
extern "C" const char *gf_preset_capture() {
    if(!active) return "";
    presetText=active->engine->capture(active->lastSeed);
    return presetText.c_str();
}
// Recall one component with its saved seed; 0 when the name is not installed.
extern "C" int gf_preset_recall(int kind,const char *name,long seed,int morph) {
    if(!active) return 0;
    active->queued.push_back({char(kind),seed});
    bool ok=active->engine->recall(char(kind),name,morph!=0);
    if(!ok) active->queued.pop_back();
    return ok;
}
extern "C" void gf_preset_clear_particles() { if(active) active->engine->clearParticles(); }
extern "C" void gf_control_state(long* values) { if(active) active->engine->state(values); }
extern "C" void gf_close() { delete active; active=nullptr; }
extern "C" double gf_fft_check() {
    AudioFFT fft; float pcm[550],spectrum[180];
    for(int i=0;i<550;i++) pcm[i]=.3f*sin(i*.07)+.2f*cos(i*.31);
    fft.run(pcm,spectrum); double maxError=0;
    for(int k=0;k<180;k++) {
        double re=0,im=0;
        for(int i=0;i<550;i++) { double a=6.283185307179586*k*i/550.; re+=pcm[i]*cos(a); im-=pcm[i]*sin(a); }
        maxError=std::max(maxError,std::abs(spectrum[k]-3.*hypot(re,im)/550.));
    }
    return maxError;
}
static EGLDisplay testDisplay=EGL_NO_DISPLAY;
static EGLContext testContext=EGL_NO_CONTEXT;
static EGLSurface testSurface=EGL_NO_SURFACE;
extern "C" int gf_headless(int w,int h) {
    auto getPlatform=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    testDisplay=getPlatform?getPlatform(EGL_PLATFORM_SURFACELESS_MESA,EGL_DEFAULT_DISPLAY,nullptr):EGL_NO_DISPLAY;
    if(testDisplay==EGL_NO_DISPLAY||!eglInitialize(testDisplay,nullptr,nullptr)) return 0;
    eglBindAPI(EGL_OPENGL_ES_API);
    const EGLint attrs[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_NONE};
    EGLConfig config; EGLint count;
    if(!eglChooseConfig(testDisplay,attrs,&config,1,&count)||count<1) return 0;
    const EGLint contextAttrs[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    testContext=eglCreateContext(testDisplay,config,EGL_NO_CONTEXT,contextAttrs);
    const EGLint surfaceAttrs[]={EGL_WIDTH,w,EGL_HEIGHT,h,EGL_NONE};
    testSurface=eglCreatePbufferSurface(testDisplay,config,surfaceAttrs);
    return eglMakeCurrent(testDisplay,testSurface,testSurface,testContext);
}
extern "C" void gf_read(unsigned char *pixels,int w,int h) { glReadPixels(0,0,w,h,GL_RGBA,GL_UNSIGNED_BYTE,pixels); }
extern "C" void gf_finish() { glFinish(); }
extern "C" int gf_headless_wave_endpoints(float* values) {
    if(!active || active->waveIndices.empty() || testDisplay==EGL_NO_DISPLAY || eglGetCurrentContext()!=testContext) return 0;
    const auto &first=active->segments[active->waveIndices.front()];
    const auto &last=active->segments[active->waveIndices.back()];
    const float endpoints[]={first.sx,first.sy,first.ex,first.ey,last.sx,last.sy,last.ex,last.ey};
    std::copy(endpoints,endpoints+8,values);
    return 1;
}
extern "C" int gf_headless_fill(float value) {
    if(!active || testDisplay==EGL_NO_DISPLAY || eglGetCurrentContext()!=testContext) return 0;
    glDisable(GL_SCISSOR_TEST);
    for(int i=0;i<2;i++) {
        glBindFramebuffer(GL_FRAMEBUFFER,active->fbo[i]);
        glClearColor(value,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    }
    return glGetError()==GL_NO_ERROR;
}
extern "C" int gf_headless_history(float* values) {
    if(!active || testDisplay==EGL_NO_DISPLAY || eglGetCurrentContext()!=testContext) return 0;
    glBindFramebuffer(GL_FRAMEBUFFER,active->fbo[active->current]);
    size_t count=size_t(active->width)*active->height;
    std::vector<float> rgba(count*4);
    glReadPixels(0,0,active->width,active->height,GL_RGBA,GL_FLOAT,rgba.data());
    if(glGetError()!=GL_NO_ERROR) return 0;
    for(size_t i=0;i<count;i++) values[i]=rgba[i*4];
    return 1;
}
extern "C" void gf_headless_close() {
    eglMakeCurrent(testDisplay,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
    eglDestroySurface(testDisplay,testSurface); eglDestroyContext(testDisplay,testContext); eglTerminate(testDisplay);
}
