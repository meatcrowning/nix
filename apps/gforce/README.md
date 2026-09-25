# G-Force frontend

A Qt/GLES frontend for the early G-Force engine, with native audio capture,
rendering controls, saved looks and shared dial tuning.

The engine and original effects are by Andy O'Meara and the credited preset
authors. Boris Gjenero ported the engine to Unix; Libvisual carries that port.
Builds fetch [Libvisual revision f14b86f](https://github.com/Libvisual/libvisual/tree/f14b86f9987ca967491582a603b1cc6e8309626a/libvisual-plugins/plugins/actor/G-Force)
and apply the local compatibility/rendering patch. The original sources and
presets are not included here.

Upstream's `COPYING` notes uncertainty around the original engine's licensing
and describes its intended non-profit/hobbyist use. This frontend does not
relicense the engine. Keep the upstream notices with downloaded sources.

On the configured hosts, run `gforce`. Updates arrive through `nix-pull apply`;
the first launch after a native-source change builds the cached renderer.
