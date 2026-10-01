// The pinned AudioLoader owns playback and persistence; Home supplies another UI.
function installHomeAudioBridge(state, { setConfig, changeMenuMusic }, target) {
  let pending = Promise.resolve();
  const read = () => {
    const s = state.getPublicState();
    return { sounds: s.soundPacks.filter(p => !p.music).map(p => p.name),
      musicPacks: s.soundPacks.filter(p => p.music).map(p => p.name),
      sound: s.activeSound, soundVolume: s.soundVolume, music: s.selectedMusic,
      musicVolume: s.musicVolume, musicEnabled: s.legacyEnabled };
  };
  const api = { read, write(changes) {
    pending = pending.catch(() => {}).then(async () => {
      const before = read(), next = { ...before, ...changes };
      if (next.sound !== 'Default' && !before.sounds.includes(next.sound)) throw new Error('Unknown sound pack');
      if (next.music !== 'None' && !before.musicPacks.includes(next.music)) throw new Error('Unknown music pack');
      for (const key of ['soundVolume', 'musicVolume']) {
        if (!Number.isFinite(next[key]) || next[key] < 0 || next[key] > 1) throw new Error('Invalid volume');
      }
      if (typeof next.musicEnabled !== 'boolean') throw new Error('Invalid ambience setting');
      const result = await setConfig({ selected_pack: next.sound, selected_music: next.music,
        sound_volume: next.soundVolume, music_volume: next.musicVolume, legacy_enabled: next.musicEnabled });
      if (!result?.success || result.result !== true) throw new Error('Could not save audio settings');
      const set = state.setGlobalState.bind(state), s = state.getPublicState();
      set('activeSound', next.sound); set('soundVolume', next.soundVolume);
      set('musicVolume', next.musicVolume); set('legacyEnabled', next.musicEnabled);
      s.gainNode?.gain.setValueAtTime(next.soundVolume, s.gainNode.context.currentTime + .01);
      if (next.music !== before.music || next.musicEnabled !== before.musicEnabled) {
        changeMenuMusic(next.musicEnabled ? next.music : 'None', s.menuMusic, set,
          s.gamesRunning, s.soundPacks, next.musicVolume);
        // Preserve the selected ambience even when disabled.
        set('selectedMusic', next.music);
      } else if (s.menuMusic) s.menuMusic.volume = next.musicVolume;
      return read();
    });
    return pending;
  } };
  target.SteamHomeAudio = api;
  return () => { if (target.SteamHomeAudio === api) delete target.SteamHomeAudio; };
}
