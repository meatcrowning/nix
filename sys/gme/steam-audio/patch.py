"""Add a small, checked integration hook to the pinned AudioLoader bundle."""
from pathlib import Path
import sys

bundle, bridge, backend = map(Path, sys.argv[1:])
text = bundle.read_text()
patches = {
    '      return `/sounds_custom/${truncatedPackPath || "error"}/${fileName}`;':
        '      return homeAudioURL(`/sounds_custom/${truncatedPackPath || "error"}/${fileName}`);',
    '          args[0] = newSoundURL;':
        '          newSoundURL = homeAudioURL(newSoundURL);\n          args[0] = newSoundURL;',

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

text = backend.read_text()
old = '        packsPath = get_pack_path()'
new = old + """
        # Expose mutable packs through Decky's existing static asset route.
        assets = os.path.join(os.path.dirname(__file__), "dist", "assets")
        os.makedirs(assets, exist_ok=True)
        link = os.path.join(assets, "sounds")
        if not os.path.lexists(link):
            os.symlink(packsPath, link, True)
"""
if text.count(old) != 1:
    raise ValueError('AudioLoader backend integration point changed')
backend.write_text(text.replace(old, new))
