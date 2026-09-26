"""Settings shared by the standalone and embedded G-Force frontends."""
import math

LOOK_DIALS=('steps','sensitivity','waveResponse','trailFill','trailSharpness','persist','fadeBias','widthScale','minWidth','softness','grid','waveScale','particleScale','distortionScale','waveSmoothing','masterSpeed','flowSpeed','waveSpeed','particleSpeed','colourSpeed','hitHold')
DEFAULTS={'forceConnect':False,'forcePoints':False,'waveResponse':0.,'trailFill':1.,'trailSharpness':1.,'persist':math.log(.5)/math.log(31/32),'fadeBias':.5,'widthScale':1.,'minWidth':1.,'softness':1.,
              'grid':640,'sensitivity':1.,'steps':200,'transitionLo':4,'transitionHi':18,'rate':1.,
              'particles':True,'normalize':False,'audioOnly':False,'fps':30,
              'masterSpeed':1.,'flowSpeed':1.,'waveSpeed':1.,'particleSpeed':1.,'colourSpeed':1.,
              'waveSmoothing':1.3,'resolution':1.,'waveScale':1.,'particleScale':1.,'distortionScale':1.,'hitHold':0.,
              'intervals':{'W':[10,15],'D':[18,15],'C':[10,15],'P':[8,15]}}

# name, label, minimum, maximum, step, logarithmic scale; shared persisted units.
DIALS = [
    ('fps', 'FPS limit', 15, 120, 1, False),
    ('resolution', 'render scale', .5, 2, .25, False),
    ('steps', 'wave detail', 16, 550, 1, False),
    ('sensitivity', 'sensitivity', .1, 5, .01, True),
    ('masterSpeed', 'master speed', 0, 4, .05, False),
    ('persist', 'trail half-life (frames)', 3, 240, 1, True),
    ('widthScale', 'line width', .25, 4, .01, True),
    ('waveSmoothing', 'wave smoothing', 0, 12, .1, False),
    ('waveScale', 'wave scale', .25, 3, .025, False),
    ('particleScale', 'particle scale', .25, 3, .025, False),
    ('distortionScale', 'distortion scale', .25, 3, .025, False),
    ('flowSpeed', 'trail flow', 0, 4, .05, False),
    ('waveSpeed', 'wave motion', 0, 4, .05, False),
    ('particleSpeed', 'particle motion / lifetime', 0, 4, .05, False),
    ('colourSpeed', 'colour motion', 0, 4, .05, False),
    ('fadeBias', 'fade to black', 0, 4, .01, False),
    ('hitHold', 'hit hold (ms)', 0, 250, 5, False),
    ('trailSharpness', 'trail sharpness', 0, 1, .01, False),
    ('trailFill', 'trail fill', 1, 8, 1, False),
    ('minWidth', 'minimum width', 1, 8, .025, False),
    ('softness', 'edge softness', .25, 4, .01, True),
    ('waveResponse', 'wave response (ms)', 0, 250, 5, False),
    ('grid', 'map resolution', 128, 2048, 32, False),
    ('transitionLo', 'shortest blend (s)', 0, 30, 1, False),
    ('transitionHi', 'longest blend (s)', 0, 30, 1, False),
    ('rate', 'particle spawn rate', .1, 10, .01, True),
]
TOGGLES = [('particles', 'particles'), ('normalize', 'normalise level'),
           ('audioOnly', 'audio-reactive only'), ('forceConnect', 'force connected points'),
           ('forcePoints', 'force point count')]
PARTICLE_RATE = '.09/((NUM_PARTICLES+1)^1.66)'
