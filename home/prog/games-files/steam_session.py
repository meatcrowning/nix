"""Per-launch emulator settings; never rewrite the user's emulator config."""
from pathlib import Path


def retroarch_config():
    # SDL's GameController API gives the same button/axis numbering for every
    # Steam virtual pad. Disable autoconfig so Guide cannot return via a profile.
    settings = {
        'input_joypad_driver': 'sdl2', 'input_autodetect_enable': 'false',
        'input_driver': 'x', 'video_context_driver': '',
        'input_menu_toggle': 'f1', 'input_menu_toggle_btn': 'nul',
        # RetroArch's Start+Select combo is DualSense Options+Share.
        'input_menu_toggle_axis': 'nul', 'input_menu_toggle_gamepad_combo': '4',
        'input_enable_hotkey': 'nul', 'input_enable_hotkey_btn': 'nul',
        'input_enable_hotkey_axis': 'nul', 'input_quit_gamepad_combo': '0',
        'menu_pause_libretro': 'true', 'config_save_on_exit': 'false',
    }
    buttons = dict(b=0, a=1, y=2, x=3, select=4, start=6, l3=7, r3=8,
                   l=9, r=10, up=11, down=12, left=13, right=14)
    axes = dict(l2='+4', r2='+5', l_x_plus='+0', l_x_minus='-0',
                l_y_plus='+1', l_y_minus='-1', r_x_plus='+2', r_x_minus='-2',
                r_y_plus='+3', r_y_minus='-3')
    for port in range(1, 17):
        prefix = f'input_player{port}_'
        settings[prefix + 'joypad_index'] = str(port - 1)
        for button in sorted(buttons.keys() | axes.keys()):
            settings[prefix + button + '_btn'] = str(buttons.get(button, 'nul'))
            settings[prefix + button + '_axis'] = axes.get(button, 'nul')
    return ''.join(f'{key} = "{value}"\n' for key, value in settings.items())


def configure(game, argv, env, cache):
    if not env.get('SteamGameId', '').isdigit() or int(env['SteamGameId']) == 0:
        return argv
    if game['runner'] not in ('retroarch', 'pcsx2', 'steam-run', 'native'):
        return argv
    # Unsetting WAYLAND_DISPLAY is insufficient: libwayland then tries
    # wayland-0. An absolute nonexistent socket also covers RetroArch's native
    # Vulkan backend, which does not obey SDL_VIDEODRIVER.
    env.update(WAYLAND_DISPLAY='/nonexistent/games-steam-wayland',
               QT_QPA_PLATFORM='xcb', SDL_VIDEODRIVER='x11')
    if game['runner'] in ('retroarch', 'pcsx2'):
        # Only Valve's virtual pad, never the physical pad alongside it. Both
        # SDL2 (RetroArch) and SDL3 (PCSX2) implement this VID/PID allowlist.
        env['SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT'] = '0x28de,0x11ff'
        env['SDL_JOYSTICK_HIDAPI'] = '0'
    if game['runner'] == 'retroarch':
        config = Path(cache) / 'steam-retroarch.cfg'
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(retroarch_config())
        return [argv[0], '--appendconfig', str(config), *argv[1:]]
    return argv
