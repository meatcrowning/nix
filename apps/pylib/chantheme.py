"""The OneeChan override sheet — 4chan in this desktop's colours.

OneeChan (a 4chan userscript) bakes hex colours from its own theme into one
`<style id=ch4SS>`; its `$SS` state is a private var in a top-level IIFE, so
its theme cannot be re-driven from outside without a page RELOAD, which loses
scroll position and half-typed replies. So nothing here pokes OneeChan: we
build our OWN sheet with the SAME selectors + `!important` and let the CASCADE
win — an adopted stylesheet orders after any document `<style>`, so it beats
ch4SS on ties with nothing to out-specify.

**Two browsers, one sheet.** surfer adopts it over the `surferonee://` courier
(`apps/surfer/main.py`), and Vivaldi gets the same CSS baked into a
Tampermonkey userscript by `tools/chan-userscript.py` — which is why this
module is pure and Qt-FREE: the generator runs with no Qt, no browser and no
running app. Change a rule here and both faces move together; that is the
entire reason it is not still inside surfer.

The role->palette map (values from `docs/DESIGN.md` §3.1's twelve tokens;
§3.8's whole-palette spread): 4chan post bodies read as the primary label
(`text`), reply surfaces on the inset background (`bgAlt`), greentext and
names on the status greens (`ok`), links dim with an accent hover, subjects/
board titles/quotelinks on the accent. `chrome` adds the running KStyle's
relief on top in a Plasma session — see `_chrome_css`.
"""

from __future__ import annotations

import colorsys


def _rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rel_lum(hexstr):
    """WCAG relative luminance of a '#rrggbb' (0..1)."""
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hexstr)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a, b):
    """WCAG contrast ratio between two '#rrggbb' (1..21)."""
    la, lb = _rel_lum(a), _rel_lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _legible_link(link_hex, bg_hex, cap_hex, target=4.0):
    """The non-hovered link colour, lifted for legibility on a DARK palette.

    OneeChan's link slot is `dim`, which on a dark wallpaper sits too close to
    the page background to read comfortably (DESIGN.md §3.2 'contrast is
    measured, not judged'). On a dark palette, raise the link's HSL lightness —
    hue and saturation kept, so it stays palette-derived — until it clears a
    contrast floor against the background, capped just under the hover accent's
    luminance so the hover state still reads as brighter. A light palette (and
    the hover colour, which is `accent`) is left untouched."""
    if _rel_lum(bg_hex) > 0.2:          # light-ish background: dark mode only
        return link_hex
    link = link_hex
    if _contrast(link, bg_hex) >= target:   # already legible: leave it alone
        return link_hex
    cap = _rel_lum(cap_hex)
    for _ in range(40):
        if _contrast(link, bg_hex) >= target or _rel_lum(link) >= cap:
            break
        h, l, s = colorsys.rgb_to_hls(*(c / 255.0 for c in _rgb(link)))
        nl = min(1.0, l + 0.03)
        if nl <= l:
            break
        link = "#%02x%02x%02x" % tuple(
            round(c * 255) for c in colorsys.hls_to_rgb(h, nl, s))
    return link


def css(pal, chrome=None):
    """The whole OneeChan override sheet for one palette.

    `pal` is a name->'#rrggbb' callable over docs/DESIGN.md 3.1's twelve
    tokens; `chrome` is `kdetheme.kde_chrome()`'s dict or None. Pure and
    Qt-free, so the userscript generator can call it with no Qt at all.
    """
    p = pal
    bg = p("bg")
    reply = p("bgAlt")           # OneeChan mainColor (reply/dialog bg)
    header_bg = p("bgAlt")       # headerBGColor
    border = p("border")         # brderColor + inputbColor
    inp = p("highlight")         # inputColor (field bg)
    header_text = p("text")      # headerColor
    board = p("accent")          # boardColor
    text = p("text")             # textColor (post message body)
    # linkColor: OneeChan's `dim`, lifted for legibility on a dark palette
    # (DESIGN.md §3.2). Hover stays `accent`; a light palette is untouched.
    link = _legible_link(p("dim"), bg, p("accent"))          # linkColor
    link_h = p("accent")         # linkHColor
    header_link = _legible_link(p("dim"), header_bg, p("accent"))  # headerLColor
    ql = p("accent")             # qlColor (quotelinks)
    blink = p("info")            # blinkColor (backlinks)
    name = p("ok")               # nameColor
    trip = p("warn")             # tripColor
    title = p("accent")          # titleColor (subject)
    quote = p("ok")              # quoteColor (greentext)
    unread = p("warn")           # unreadColor
    post_hl = p("highlight")     # postHLColor
    replyslct = p("accent")      # replyslctColor
    # On a LIGHT palette, OneeChan's inset surfaces should read as the plain
    # PAGE background, not the `bgAlt`/`highlight` shades: those are tuned as
    # insets against a DARK page (DESIGN.md §3.1's value ladder), so on a
    # light wallpaper they land as dark/near-black patches behind post
    # headers, open reply chains, catalog panels, post bodies and text
    # fields. Collapse reply/header/field backgrounds to `bg` there; a dark
    # palette keeps the inset treatment. Same light-ness test as
    # _legible_link (which conversely leaves the light-palette link alone).
    light = _rel_lum(bg) > 0.2
    if light:
        reply = header_bg = inp = bg
    i = "!important"
    parts = [
        # --- text colours ---
        "html,body,div.boardBanner,#menu,input:not(.jsColor),textarea,"
        "#qr-filename-container,#post-preview,.post-last,.pln,select,"
        ".captcha-root,.tegaki-label,.dd-menu ul,.boxbar{color:%s%s}" % (text, i),
        ".nameBlock:not(.capcodeMod)>.name,.com,.post-author{color:%s%s}" % (name, i),
        ".nameBlock>.postertrip,.post-tripcode,.tag{color:%s%s}" % (trip, i),
        "a,.typ,.atn,body.is_catalog .button,:root.catalog-mode .button,"
        ".options-button,.tegaki-tb-btn{color:%s%s}" % (link, i),
        "a:hover,body.is_catalog .button:hover,:root.catalog-mode .button:hover,"
        ".lit,.tegaki-tb-btn:hover{color:%s%s}" % (link_h, i),
        "#header-bar,a.current{color:%s%s}" % (header_text, i),
        "#header-bar a:not(.current){color:%s%s}" % (header_link, i),
        ".postMessage>.quote,s:hover .quote,.str,.atv,.new,"
        ".catalog-thread>.comment>.quote{color:%s%s}" % (quote, i),
        ".subject,.replytitle,.teaser b,.post-subject,"
        ".option.header .option-title,.kwd{color:%s%s}" % (title, i),
        ".boardTitle{color:%s%s}" % (board, i),
        "#boardNavDesktop,#boardNavDesktopFoot{color:%s%s}" % (header_text, i),
        ".backlink{color:%s%s}" % (blink, i),
        ".quotelink{color:%s%s}" % (ql, i),
        # A post's own number is navigation chrome, not a quotelink: it sits
        # beside the timestamp and should carry the same primary ink.  The
        # actual >> reference remains a `.quotelink` in the post body.
        # OneeChan's selected-theme custom CSS uses
        # `span.postNum.desktop > a`; retain that shape and add the post-info
        # parent so this wins even when OneeChan injects its stylesheet later.
        ".postInfo span.postNum.desktop>a,.postInfo span.postNum.desktop>a:hover{"
        "color:%s%s;opacity:1%s}" % (text, i, i),
        # --- backgrounds ---
        "body{background:%s%s}" % (bg, i),
        # `.inline` and the catalog cells (`Show Background` mode) are
        # reply-type insets OneeChan also paints from `mainColor`, but they
        # were never mapped here — so on a dark palette they kept OneeChan's
        # baked colour un-themed, and on a light one they rendered as the raw
        # dark inset (near-black on his cream page). Fold them in so they
        # follow `reply` too: `bgAlt` on dark, collapsed to `bg` on light.
        # Selectors are verbatim (catalog's is `:root.catalog-background …`),
        # since a bare `.catalog-thread` loses on specificity to OneeChan's.
        ".reply,body.is_catalog .panel,:root.catalog-mode .panel,.dialog,"
        ".tab-label,#post-preview,#tegaki,.boxbar,.inline,"
        ":root.catalog-background #threads div.thread,"
        ":root.catalog-background .catalog-thread,"
        ":root.op-background .postContainer.opContainer,"
        ".dd-menu ul{background:%s%s}" % (reply, i),
        ":root:not(.header-gradient) #header-bar,"
        ":root.header-gradient #header-bar{background:%s%s}" % (header_bg, i),
        "input:not(.jsColor),textarea,.riceCheck,#qr-filename-container,select,"
        ".captcha-root{background:%s%s}" % (inp, i),
        # OneeChan brightens every field on hover.  Fields are stable surfaces
        # here: focus gets the border state below, but merely crossing a field
        # must not repaint its fill.
        "input:not(.jsColor):hover,textarea:hover,.riceCheck:hover,"
        "#qr-filename-container:hover,select:hover,.captcha-root:hover{"
        "background:%s%s}" % (inp, i),
        # Its options panel darkens every other main row from `mainColor`.
        # That makes a light desktop palette read as black zebra stripes.
        "#oneechan-options #main-section>.option:nth-of-type(even){background:%s%s}" % (reply, i),
        # OneeChan gives its option-panel actions its own mainColor fill.
        # They are anchor buttons, so the real-button rule below cannot reach
        # them; keep their resting and hover surfaces on the page instead of
        # leaving black pills in an otherwise desktop-matched panel.
        "#oneechan-options .options-button,#oneechan-options .options-button:hover,"
        ".qr-link,.qr-link:hover,.pages.cataloglink,.pages.cataloglink:hover,"
        ".pages strong>a,.pages strong>a:hover{background:%s%s}" % (reply, i),
        # --- borders ---
        ".reply,:root.op-background .postContainer.opContainer,.dialog,.entry,"
        ".inline,fieldset,#post-preview,select{border-color:%s%s}" % (border, i),
        "input,textarea,.riceCheck,#qr-filename-container,#search-box,"
        "#index-search,select,#post-preview,.captcha-root,"
        ".dd-menu ul{border-color:%s%s}" % (border, i),
        "input:focus,textarea:focus,#qr-filename-container:focus,select:focus,"
        ".captcha-root:focus{border-color:%s%s}" % (link, i),
        # The per-post header strip carries a `border-bottom` (near-black in
        # OneeChan's ch4SS) that reads as a rule down the middle of every
        # post, splitting the `.postInfo` header from the post body. Drop it
        # on every palette so header and body read as one block — this is the
        # separating line only; the dark-palette header-vs-body inset (the
        # `.postInfo` tint) is untouched, and the light collapse below still
        # folds that tint into the page bg.
        ".postInfo{border-bottom:none%s}" % i,
        # --- highlights ---
        ".highlight{outline-color:%s%s}" % (replyslct, i),
        ":root.hl-border .post.reply,"
        ":root.op-background.hl-border .postContainer.opContainer{"
        "border-left-color:%s%s}" % (post_hl, i),
        "#unread-line{background-image:linear-gradient(to left,"
        "transparent,%s,transparent)%s}" % (unread, i),
    ]
    if light:
        # The per-post header strip. OneeChan paints `.postInfo` from
        # `mainColor` too — `background:rgba(mainColor,.2)` — and the
        # `.reply` collapse above only reaches the post body, so on a light
        # page the strip stays a grey tint over cream: "post headers still
        # darker than the background". Collapse the tint to the page `bg`;
        # light-palette only, so a dark palette keeps OneeChan's
        # header-vs-body inset. (The separating border-bottom is dropped for
        # every palette above, not here.)
        parts.append(
            ".postInfo{background:%s%s}" % (bg, i))
    parts.extend(_chrome_css(chrome, i))
    return "".join(parts)


def _chrome_css(ch, i):
    """The KStyle relief layer: 4chan drawn as a window of the running KDE
    style, gradients and all.

    In a Plasma session the desktop's look is not this design language's —
    it is whatever Global Theme is picked in System Settings, and
    DESIGN.md 7.6's answer to that is "we do not imitate the system theme;
    we let the system theme paint". A web page is the one surface where
    that is impossible: no QStyle will ever paint 4chan. So this is the
    deliberate exception — imitation, because the alternative is the one
    flat window in a session of gradient ones.

    `kdetheme.kde_chrome()` returns None outside a Plasma session and under
    a flat KStyle (Breeze, Fusion), so the HYPRLAND look is untouched and
    stays flat: DESIGN.md 2's "no gradients" is a rule about THIS desktop,
    and this layer only ever runs in the other one.

    Every selector here is repeated VERBATIM from the flat layer above, so
    the two tie on specificity and source order decides — this one is later,
    so it wins, and nothing has to be out-specified.
    """
    if not ch:
        return []
    def grad(a, b):
        return "linear-gradient(to bottom,%s,%s)" % (ch[a], ch[b])
    bevel, shade, r = ch["bevel"], ch["shade"], ch["radius"]
    panel = grad("panelTop", "panelBottom")
    return [
        # The window gradient. Oxygen paints it on the WINDOW — light at the
        # top, settling into the base a few hundred px down — so it is
        # pinned to the viewport (`fixed`) and the page scrolls under it,
        # rather than running the height of a 300-post thread.
        "body{background-color:%s%s;background-image:linear-gradient("
        "to bottom,%s,%s 320px)%s;background-repeat:no-repeat%s;"
        "background-attachment:fixed%s}"
        % (ch["windowBottom"], i, ch["windowTop"], ch["windowBottom"], i, i, i),
        # Dialogs, catalog cells, previews and menus as the style's slabs:
        # the panel gradient, a 1px light bevel along the top, a soft foot
        # shadow and Oxygen's small corner radius. POSTS are deliberately not
        # in this list — see the rule below.
        "body.is_catalog .panel,:root.catalog-mode .panel,.dialog,"
        ".tab-label,#post-preview,#tegaki,.boxbar,"
        ":root.catalog-background #threads div.thread,"
        ":root.catalog-background .catalog-thread,"
        ".dd-menu ul{background:%s%s;border-radius:%dpx%s;"
        "box-shadow:inset 0 1px 0 %s,0 1px 2px %s%s}"
        % (panel, i, r, i, bevel, shade, i),
        # Posts are NOT slabs. A thread is a column of them, so slabbing each
        # one tiles the panel gradient down the page and the window gradient
        # this layer's whole point is never seen. Posts (and their header
        # strips and inline quotes) drop background, border and shadow
        # instead, and the fixed body gradient reads through them.
        ".reply,.inline,:root.op-background .postContainer.opContainer,"
        ".postInfo{background:none%s;background-color:transparent%s;"
        "border:none%s;box-shadow:none%s}" % (i, i, i, i),
        # ...except the "you were quoted"/selection marker, which the rule
        # above would take with it: it is the only border a post keeps.
        ":root.hl-border .post.reply,"
        ":root.op-background.hl-border .postContainer.opContainer{"
        "border-left-style:solid%s;border-left-width:4px%s}" % (i, i),
        # The board header reads as the style's toolbar.
        ":root:not(.header-gradient) #header-bar,"
        ":root.header-gradient #header-bar{background:%s%s;"
        "box-shadow:inset 0 1px 0 %s,0 1px 3px %s%s}"
        % (grad("headerTop", "headerBottom"), i, bevel, shade, i),
        # Text fields are the style's HOLE: sunken, not raised — the bevel
        # goes to a shadow at the top and there is no foot highlight.
        "input:not(.jsColor),textarea,.riceCheck,#qr-filename-container,select,"
        ".captcha-root{background:%s%s;border-radius:%dpx%s;"
        "box-shadow:inset 0 1px 2px %s%s}"
        % (ch["panelBottom"], i, r, i, shade, i),
        # This block is after the flat layer, so it must carry the stable-hover
        # rule too.  Otherwise Plasma's sunken field colour replaces the flat
        # resting fill, while the earlier :hover rule wins on specificity and
        # flips the field back to the page background.
        "input:not(.jsColor):hover,textarea:hover,.riceCheck:hover,"
        "#qr-filename-container:hover,select:hover,.captcha-root:hover{"
        "background:%s%s}" % (ch["panelBottom"], i),
        # Real buttons and OneeChan's anchor actions take the same desktop
        # button surface.  The latter are what Save/Cancel/Export use; without
        # including them they retain OneeChan's black mainColor background.
        # This follows the field rule, so submit inputs do not land in the
        # sunken field surface.
        "button,input[type=submit],input[type=button],input[type=reset],"
        "#oneechan-options .options-button,#oneechan-options .options-button:hover,"
        ".qr-link,.qr-link:hover,.pages.cataloglink,.pages.cataloglink:hover,"
        ".pages strong>a,.pages strong>a:hover{"
        "background:%s%s;border-radius:%dpx%s;"
        "box-shadow:inset 0 1px 0 %s,0 1px 2px %s%s}"
        % (grad("buttonTop", "buttonBottom"), i, r, i, bevel, shade, i),
    ]
