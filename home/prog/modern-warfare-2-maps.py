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
    button = '''
        CHOICE_BUTTON_FOCUS(7, "nix_random_map", "Random map", setdvar "nix_random_map" 1; close "settings_map"; close "self";, LOCAL_MAP_FOCUS("Random map", "Revealed when the match starts", "loadscreen_mp_bonusmaps"), ;)

'''
    # Custom map selection bypasses LOCAL_MAP_ACTION.
    menu = menu.replace('uiScript "ApplyMap";', 'setdvar "nix_random_map" 0; uiScript "ApplyMap";')
    return menu.replace(marker, button + marker, 1)


def render_lobby(menu, maps):
    # Sample once at Start, never when opening the picker or drawing a frame.
    # The pool is shuffled with OS randomness at launch; UI expressions supply
    # the activation time because this engine has no UI random() expression.
    actions = [f'setLocalVarInt "nix_random_map_index" (milliseconds() % {len(maps)});']
    # Leave the dvar name unquoted: the preprocessor joins adjacent strings.
    actions += [f'if (localvarint("nix_random_map_index") == {i}) '
                f'{{ setdvar ui_mapname "{name}"; }}' for i, name in enumerate(maps)]
    actions += ['execNow "xupdatepartystate";']
    original = 'exec xpartygo;'
    if menu.count(original) != 1:
        raise ValueError('Unexpected upstream match start action')
    added = 'if (dvarstring("nix_random_map") == "1") {\n' + '\n'.join(actions) + '\n}\n'
    menu = menu.replace(original, added + original, 1)
    for needle, expression in [('"preview_" + dvarstring(ui_mapname)', 'material "loadscreen_mp_bonusmaps";'),
                               ('dvarstring(party_mapname)', 'text "Random map";')]:
        position = menu.index(needle)
        start = menu.rfind('        itemDef', 0, position)
        end = menu.index('        }', position) + len('        }')
        block = menu[start:end]
        normal = re.sub(r'visible\s+1', 'visible when (dvarstring("nix_random_map") != "1")', block)
        hidden = re.sub(r'exp (material|text)[^\n]+', 'exp ' + expression, block)
        hidden = re.sub(r'visible\s+1', 'visible when (dvarstring("nix_random_map") == "1")', hidden)
        menu = menu[:start] + normal + '\n' + hidden + menu[end:]
    # Unlinker's legacy dump leaves expression tails outside parentheses;
    # IW4x's disk-menu parser otherwise stops after the first subexpression.
    return re.sub(r'^(\s*exp\s+(?:rect\s+[xywh]|forecolor\s+[rgba]|material|text))\s+([^\n]+);$',
                  lambda m: m[1] + ' (' + m[2] + ')', menu, flags=re.MULTILINE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.game / 'main/iw4x/x86/iw4x_00.iwd') as archive:
        menu = archive.read('ui_mp/settings_map.menu').decode().replace('\r\n', '\n')
        macros = archive.read('ui_mp/mapmacros.inc').decode().replace('\r\n', '\n')
    lobby = (args.game / '.nix-menu-source/ui_mp/menu_xboxlive_privatelobby.menu').read_text()
    maps = installed_maps(args.game, menu)
    if not maps:
        raise ValueError('No installed multiplayer maps found')
    random.SystemRandom().shuffle(maps)
    outputs = {'settings_map.menu': render_menu(menu, maps),
               'menu_xboxlive_privatelobby.menu': render_lobby(lobby, maps),
               'mapmacros.inc': macros.replace('setdvar ui_mapname mapname;',
                   'setdvar "nix_random_map" 0; setdvar ui_mapname mapname;')}
    for name, content in outputs.items():
        output = args.game / 'mods/mp_bots/ui_mp' / name
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + '.tmp')
        temporary.write_text(content)
        temporary.replace(output)
    print(f'Random map: {len(maps)} installed maps')


if __name__ == '__main__':
    main()
