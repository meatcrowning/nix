import QtQuick

// The player's ONE track context menu (docs/DESIGN.md §7.1: everything
// selectable is right-clickable). Every place a track is drawn — the queue, an
// album section, a smart playlist, the search results, the now-playing header —
// opens THIS, so the vocabulary and the ordering cannot drift apart between the
// five listings the way five hand-written menus would.
//
// It is a CtxMenu (§7.2 owns the look) that knows the player's verbs; the
// arrangement follows §7.2's ordering rule — the play actions first, navigation
// next, and the one destructive entry LAST behind a separator, so the pointer
// never lands on "remove from queue".
//
// Honesty, per §7.2: an action that cannot work here is ABSENT when the whole
// site can never offer it (no "remove from queue" outside the queue, no "go to
// album" inside an album's own section) and DISABLED when it is this row that
// cannot do it (a missing file, an untagged artist, no filer on PATH). Nothing
// is ever drawn as if it would work and then quietly does nothing.
//
//   openForTrack(x, y, ctx)   x/y in THIS item's coordinates — callers parent
//                             it to the window's contentItem and map through it,
//                             so a menu opened from a 240px-wide queue column is
//                             still sized and clamped against the whole window.
//
// ctx fields (all optional except trackId):
//   trackId, artist, albumId, available   straight off the row
//   playNow      function() — the site's own "play this row" (the same thing
//                double-click does). Omitted entirely for the now-playing
//                header, where the row is already playing.
//   queueIndex   >= 0 when the row IS a queue row  -> "remove from queue"
//   inAlbum      album id this listing already shows -> "go to album" dropped
//   openAlbum    function(albumId)      -> "go to album"
//   browseArtist function(artistName)   -> "search for artist"
CtxMenu {
    id: root

    function openForTrack(x, y, c) {
        var id = c.trackId;
        var artist = c.artist || "";
        var albumId = c.albumId || 0;
        var have = c.available !== false;      // the file is still there
        var queued = Player.queueLength > 0;
        var items = [];

        if (c.playNow)
            items.push({ label: "play now", enabled: have, trigger: c.playNow });
        // "next" needs something to be next TO: with an empty queue the entry
        // would just be a second "play now" under a name that lies.
        items.push({ label: "play next", enabled: have && queued,
                     trigger: function () { Player.playNext([id]); } });
        items.push({ label: "add to queue", enabled: have,
                     trigger: function () { Player.queueTracks([id]); } });
        items.push({ label: "shuffle artist", enabled: artist !== "",
                     trigger: function () { Player.playArtistShuffled(artist); } });

        items.push({ separator: true });

        if (c.openAlbum && albumId !== (c.inAlbum || 0))
            items.push({ label: "go to album", enabled: albumId > 0,
                         trigger: function () { c.openAlbum(albumId); } });
        if (c.browseArtist)
            items.push({ label: "search for artist", enabled: artist !== "",
                         trigger: function () { c.browseArtist(artist); } });
        items.push({ label: "open folder in filer",
                     enabled: have && Library.canReveal,
                     trigger: function () { Library.revealTrack(id); } });

        if ((c.queueIndex !== undefined ? c.queueIndex : -1) >= 0) {
            var qi = c.queueIndex;
            items.push({ separator: true });
            items.push({ label: "remove from queue",
                         trigger: function () { Player.removeFromQueue([qi]); } });
        }

        root.open(x, y, items);
    }
}
