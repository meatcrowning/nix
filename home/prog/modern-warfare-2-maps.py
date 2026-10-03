"""Add an installed-map shuffle button to IW4x's existing map picker."""
import argparse
from pathlib import Path
import random
import re
import zipfile


def installed_maps(game, menu):
    candidates = set(re.findall(r'LOCAL_MAP_SELECTION\(\s*\d+,\s*"(mp_[a-zA-Z0-9_]+)"', menu))
    zones = {p.stem for p in (game / 'zone').rglob('*.ff') if p.stat().st_size}
    available = {name for name in candidates if name in zones and name + '_load' in zones}
    # Match IW4x's usermap directory convention; never treat load/team zones
    # or single-player fastfiles as playable multiplayer maps.
    for directory in (game / 'usermaps').glob('*'):
        name = directory.name
        if not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_-]*', name):
            continue
        fastfile = directory / (name + '.ff')
        if fastfile.is_file() and fastfile.stat().st_size:
            available.add(name)
    return sorted(available)


def render_menu(menu, maps):
    marker = '\t\tLOCAL_MAP_SELECTION(0,'
    if marker not in menu or '"nix_random_map"' in menu:
        raise ValueError('Unexpected upstream map menu')
    if not maps:
        return menu
    # UI expressions have no RNG. The launcher supplies a fresh shuffled bag;
    # advancing only on activation makes every map reachable without repeats.
    actions = '\n'.join(
        f'            if ( localvarint("nix_random_map_index") == {i} ) '
        f'{{ setdvar "ui_mapname" "{name}"; }}'
        for i, name in enumerate(maps))
    actions += f'\nsetLocalVarInt "nix_random_map_index" ( (localvarint("nix_random_map_index") + 1) % {len(maps)} );'
    actions += '\nclose "settings_map";\nclose "self";'
    button = '\n#define NIX_RANDOM_MAP_ACTION \\\n' + ' \\\n'.join(actions.splitlines()) + '\n'
    button += '''
        CHOICE_BUTTON_FOCUS(7, "nix_random_map", "Random map", NIX_RANDOM_MAP_ACTION, LOCAL_MAP_FOCUS("Random map", "Choose from all installed maps", "loadscreen_mp_bonusmaps"), ;)
#undef NIX_RANDOM_MAP_ACTION

'''
    return menu.replace(marker, button + marker, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.game / 'main/iw4x/x86/iw4x_00.iwd') as archive:
        menu = archive.read('ui_mp/settings_map.menu').decode().replace('\r\n', '\n')
    maps = installed_maps(args.game, menu)
    random.SystemRandom().shuffle(maps)
    output = args.game / 'mods/mp_bots/ui_mp/settings_map.menu'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.menu.tmp')
    temporary.write_text(render_menu(menu, maps))
    temporary.replace(output)
    print(f'Random map: {len(maps)} installed maps')


if __name__ == '__main__':
    main()
