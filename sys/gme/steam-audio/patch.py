"""Add a small, checked integration hook to the pinned AudioLoader bundle."""
from pathlib import Path
import sys

bundle, bridge, backend = map(Path, sys.argv[1:])
text = bundle.read_text()
patches = {
    '  function changeMenuMusic(newMusic, menuMusic, setGlobalState, gamesRunning, soundPacks, musicVolume) {':
        '  const bigPictureMode = 4;\n'
        '  let inBigPicture = false;\n'
        '  function changeMenuMusic(newMusic, menuMusic, setGlobalState, gamesRunning, soundPacks, musicVolume) {',
    '          menuMusic.currentTime = 0;\n          setGlobalState("menuMusic", null);':
        '          menuMusic.onended = null;\n'
        '          menuMusic.currentTime = 0;\n          setGlobalState("menuMusic", null);',
    '      if (newMusic !== "None" && gamesRunning.length === 0) {':
        '      if (inBigPicture && newMusic !== "None" && gamesRunning.length === 0) {',
    '      return `/sounds_custom/${truncatedPackPath || "error"}/${fileName}`;':
        '      return homeAudioURL(`/sounds_custom/${truncatedPackPath || "error"}/${fileName}`);',
    '          args[0] = newSoundURL;':
        '          newSoundURL = homeAudioURL(newSoundURL);\n          args[0] = newSoundURL;',

    '  var index = deckyFrontendLib.definePlugin((serverApi) => {':
        bridge.read_text() + '\n  var index = deckyFrontendLib.definePlugin((serverApi) => {',
    '      getAndSetSoundPacks().then(() => {':
        '      let removeHomeBridge = () => {};\n'
        '      const updateMusicMode = (mode) => {\n'
        '          const next = mode === bigPictureMode;\n'
        '          if (next === inBigPicture) return;\n'
        '          inBigPicture = next;\n'
        '          const { legacyEnabled, selectedMusic, menuMusic, gamesRunning, soundPacks, musicVolume } = state.getPublicState();\n'
        '          if (menuMusic || legacyEnabled) {\n'
        '              changeMenuMusic(selectedMusic, menuMusic, setGlobalState, gamesRunning, soundPacks, musicVolume);\n'
        '          }\n'
        '      };\n'
        '      let observedMode = false;\n'
        '      const musicModeRegistrar = SteamClient.UI.RegisterForUIModeChanged((mode) => {\n'
        '          observedMode = true;\n'
        '          updateMusicMode(mode);\n'
        '      });\n'
        '      Promise.resolve(SteamClient.UI.GetUIMode()).then((mode) => {\n'
        '          if (!observedMode) updateMusicMode(mode);\n'
        '      }, () => {});\n'
        '      getAndSetSoundPacks().then(() => {',
    '              setGlobalState("legacyEnabled", configLegacyEnabled);':
        '              setGlobalState("legacyEnabled", configLegacyEnabled);\n'
        '              removeHomeBridge = installHomeAudioBridge(state, {setConfig, changeMenuMusic}, window);',
    '          onDismount: () => {\n              const { menuMusic, soundPatchInstance, volumePatchInstance }':
        '          onDismount: () => {\n'
        '              musicModeRegistrar.unregister();\n'
        '              observedMode = true;\n'
        '              updateMusicMode(-1);\n'
        '              removeHomeBridge();\n              const { menuMusic, soundPatchInstance, volumePatchInstance }',
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
