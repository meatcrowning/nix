#pragma once
#include <libindicator/indicator-object.h>
typedef gboolean (*NowPlayingHovered)(gpointer panel, IndicatorObject *indicator);
IndicatorObject *now_playing_new(NowPlayingHovered hovered, gpointer panel);
