# Spec Ops controller extension

`modern-warfare-2.nix` builds the 32-bit Windows loader and DLL for top's
offline IW4x-SP installation. The launcher checks both executable hashes;
the DLL checks instruction bytes before patching SP159. An upstream client
update requires reviewing these hooks before changing the hashes.

The DLL chains AlterWare's main-frame scheduler, polls Wine XInput, and adds
analog movement and view angles before the engine finalizes `usercmd_s`.
Buttons use the game's command buffer; menus use its key-event function.
There are no desktop input events. Losing focus, disconnecting, or entering
a menu releases the extension's held commands. Menu confirmation is suppressed
on transition into gameplay until the button is released.

The layout matches multiplayer's default controller bindings. The settings
helper imports sensitivity, inversion, deadzones, turn rates, and assist
toggles once. Controller assistance uses SP's visible aim-target list for
slowdown and relative-velocity tracking; it does not alter mouse movement.
Contextual binding directives display PlayStation button **names**, not icon
textures. Hardcoded keyboard text and the keyboard binding editor are unchanged.

`test.c` runs during the Nix build. `test-native.c` exercises the actual input
handler with private memory and command/key sinks; its packaged executable is
under `libexec/`. Run it only in a disposable Wine prefix on an isolated
display, with audio and physical input devices masked. Mission smoke tests
must also use copied profiles, an isolated display and network, and read-only
game assets. Controller feel and visual checks belong to the user.
