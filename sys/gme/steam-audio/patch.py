"""Add a small, checked integration hook to the pinned AudioLoader bundle."""
from pathlib import Path
import sys

bundle, bridge = map(Path, sys.argv[1:])
text = bundle.read_text()
patches = {
    '  var index = deckyFrontendLib.definePlugin((serverApi) => {':
        bridge.read_text() + '\n  var index = deckyFrontendLib.definePlugin((serverApi) => {',
    '      getAndSetSoundPacks().then(() => {':
        '      let removeHomeBridge = () => {};\n      getAndSetSoundPacks().then(() => {',
    '              setGlobalState("legacyEnabled", configLegacyEnabled);':
        '              setGlobalState("legacyEnabled", configLegacyEnabled);\n'
        '              removeHomeBridge = installHomeAudioBridge(state, {setConfig, changeMenuMusic}, window);',
    '          onDismount: () => {\n              const { menuMusic, soundPatchInstance, volumePatchInstance }':
        '          onDismount: () => {\n              removeHomeBridge();\n              const { menuMusic, soundPatchInstance, volumePatchInstance }',
}
for old, new in patches.items():
    if text.count(old) != 1:
        raise ValueError('AudioLoader integration point changed')
    text = text.replace(old, new)
bundle.write_text(text)
