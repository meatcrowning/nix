"""Build the pinned upstream engine plus local renderer into an immutable cache."""
import fcntl
import hashlib
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parent
UPSTREAM_SHA256='62f0a45a8fef1bd85b3db5cd2b920481b2fae25f95f6bc0f09c6b4566f0462f9'
BUILD_FILES=('build.py','renderer.cpp','gpu_hooks.h','config.h','libvisual.h','engine.patch')


def prepare():
    archive=Path(os.environ['GF_ENGINE_ARCHIVE'])
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=UPSTREAM_SHA256:
        raise RuntimeError('upstream archive checksum mismatch')
    digest=hashlib.sha256()
    for name in BUILD_FILES:
        digest.update(name.encode());digest.update((ROOT/name).read_bytes())
    cc=os.environ.get('CC','cc');cxx=os.environ.get('CXX','c++')
    identity=(platform.machine(),cc,cxx,os.environ.get('CPATH',''),os.environ.get('LIBRARY_PATH',''))
    digest.update(repr(identity).encode())
    cache=Path(os.environ.get('GF_BUILD_CACHE',str(Path.home()/'.cache/gforce-build')))
    cache.mkdir(parents=True,exist_ok=True)
    build=cache/digest.hexdigest()[:24]
    with (cache/'build.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        library=build/'renderer.so'
        if library.is_file():return library
        # A failed build may be retried. Only our incomplete cache entry is replaced.
        if build.exists():shutil.rmtree(build)
        build.mkdir()
        log=build/'build.log'
        print(f'gforce: building renderer; log: {log}',file=__import__('sys').stderr,flush=True)
        try:
            with tarfile.open(archive) as source:
                source.extractall(build,filter='data')
            extracted=next(build.glob('libvisual-*'))
            extracted.rename(build/'source')
            with log.open('w') as output:
                def run(args):subprocess.run(args,cwd=build/'source',stdout=output,stderr=subprocess.STDOUT,check=True)
                run([os.environ.get('GF_PATCH','patch'),'--batch','--forward','-p1','-i',str(ROOT/'engine.patch')])
                src=build/'source/libvisual-plugins/plugins/actor/G-Force'
                data=build/'data';data.mkdir()
                shutil.copy2(src/'deffont',data/'deffont')
                for kind in ('ColorMaps','DeltaFields','Particles','WaveShapes'):
                    dest=data/('GForce'+kind);dest.mkdir()
                    for preset in (src/('GForce'+kind)).iterdir():
                        if preset.is_file() and preset.name!='Makefile.am':shutil.copy2(preset,dest/preset.name)
                include=build/'include/libvisual';include.mkdir(parents=True)
                shutil.copy2(ROOT/'libvisual.h',include/'libvisual.h')
                state=build/'state';state.mkdir()
                inc=[ROOT,build/'source/libvisual-plugins',src/'Common',src/'unix/Headers',src/'unix/libmfl',src/'GForceCommon/Headers',build/'include']
                sources=[]
                for area in ('GeneralTools','UI','io','math'):
                    directory=src/'Common'/area;inc.append(directory/'Headers')
                    line=next(x for x in (directory/'Makefile.am').read_text().splitlines() if x.startswith('ALLSOURCES ='))
                    sources.extend(str(directory/name) for name in shlex.split(line.split('=',1)[1]))
                sources.extend(str(src/'GForceCommon'/name) for name in ('DeltaField.cpp','G-Force.cpp','GF_Palette.cpp','GForcePixPort.cpp','ParticleGroup.cpp','WaveShape.cpp'))
                flags=['-I'+str(p) for p in inc]+[f'-DGF_DEMO_STATE_DIR="{state}"']
                run([cc,'-O2','-fPIC','-DUNIX_X',*flags,'-c',str(src/'unix/libmfl/mfl.c'),'-o',str(build/'mfl.o')])
                pending=build/'renderer.pending.so'
                run([cxx,'-std=gnu++17','-O2','-fno-strict-aliasing','-g','-fPIC','-shared','-fpermissive','-Wno-multichar','-Wno-write-strings','-DUNIX_X','-DHAVE_CONFIG_H',f'-DDATADIR="{data}"',*flags,*sources,str(ROOT/'renderer.cpp'),str(build/'mfl.o'),'-lGLESv2','-lEGL','-l:libfftw3f.so.3','-o',str(pending)])
                pending.rename(library)
        except (OSError,subprocess.CalledProcessError) as exc:
            raise RuntimeError(f'build failed; see {log}') from exc
        return library


if __name__=='__main__':
    print(prepare())
