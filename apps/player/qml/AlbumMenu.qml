import QtQuick

// The player's ONE album context menu (docs/DESIGN.md §7.1: everything
// selectable is right-clickable). Both places a cover is drawn — the gallery
// and the now-playing page's album browser — open THIS, so the vocabulary and
// the ordering cannot drift apart the way two hand-written menus would. It is
// the album twin of TrackMenu.qml, and it followed the same history: the menu
// was written inline in the gallery, and the second grid of covers is what
// made keeping one copy load-bearing.
//
// A CtxMenu (§7.2 owns the look) that knows the player's album verbs, ordered
// by §7.2: play actions first, navigation next, the desktop-wide and the
// destructive entries LAST behind separators, so the pointer never lands on
// one when the menu opens. An action that cannot work is DISABLED, never drawn
// as if it would work and then quietly doing nothing (§10).
//
//   openForAlbum(x, y, ctx)      one cover
//   openForSelection(x, y, ctx)  a ctrl/shift-picked set
//
// x/y are in THIS item's coordinates: map through it (`mapToItem(albumMenu,
// …)`), so a menu opened from a 300px browser column is still sized and
// clamped against whatever it is parented to.
//
// ctx fields — openForAlbum: albumId, artist, isOpen (this cover's section is
// the one showing), open: function(albumId) (0 closes), searchArtist,
// editAliases, all optional but albumId. openForSelection: ids, clearSelection.
CtxMenu {
    id: root

    function openForAlbum(x, y, c) {
        var aid = c.albumId;
        var artist = c.artist || "";
        var items = [
            // start=-1: no chosen track, so shuffle (if on) pins nothing —
            // see playTracks.
            { label: "play", trigger: function () { Player.playAlbum(aid, -1); } },
            { label: "play shuffled",
              trigger: function () { Player.setShuffle(true); Player.playAlbum(aid, -1); } },
            // The track menu's "play next" is the whole-album twin of this —
            // both insert after the playing row, and both grey with an empty
            // queue, because with nothing playing it is a second "play".
            { label: "play next", enabled: Player.queueLength > 0,
              trigger: function () { Player.playAlbumNext(aid); } },
            { label: "add to queue", trigger: function () { Player.queueAlbum(aid); } },
            { separator: true },
        ];
        if (c.open)
            items.push({ label: c.isOpen ? "close album" : "open album",
                         trigger: function () { c.open(c.isOpen ? 0 : aid); } });
        if (c.searchArtist)
            items.push({ label: "search artist", enabled: artist !== "",
                         trigger: function () { c.searchArtist(artist); } });
        if (c.editAliases)
            items.push({ label: "same person as...", enabled: artist !== "",
                         trigger: function () { c.editAliases(artist); } });
        items.push({ separator: true });
        // Applies the theme desktop-wide, so it sits behind a separator like
        // any other action with a wide blast radius.
        items.push({ label: "create systheme",
                     // `=== true`, not a bare truth test: `canSystheme`
                     // missing makes the whole expression `undefined`, and
                     // CtxMenu reads "not false" as enabled — so the row was
                     // OFFERED, and would have done nothing (§10, never offer
                     // an action that can silently fail).
                     enabled: Library.canSystheme === true
                              && !!Library.albumInfo(aid).fullArt,
                     trigger: function () { Library.createSysthemeFromAlbum(aid); } });
        items.push({ separator: true });
        items.push({ label: "move album to trash",
                     trigger: function () { Library.trashAlbum(aid); } });
        open(x, y, items);
    }

    function openForSelection(x, y, c) {
        var sel = (c.ids || []).slice(), n = sel.length;
        open(x, y, [
            { label: "play " + n + " albums",
              trigger: function () { Player.playAlbums(sel, -1); } },
            { label: "play " + n + " albums shuffled",
              trigger: function () { Player.setShuffle(true); Player.playAlbums(sel, -1); } },
            { label: "play " + n + " albums next", enabled: Player.queueLength > 0,
              trigger: function () { Player.playAlbumsNext(sel); } },
            { label: "add " + n + " albums to queue",
              trigger: function () { Player.queueAlbums(sel); } },
            { separator: true },
            { label: "clear selection",
              trigger: function () { if (c.clearSelection) c.clearSelection(); } },
        ]);
    }
}
