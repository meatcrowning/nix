"""The Twitter/X override sheet — X in this desktop's live palette.

This intentionally targets X's stable semantic hooks (`data-testid`, landmark
roles and the primary/secondary columns) rather than its generated class
names.  Those hooks survive X's regular CSS bundle churn; if a future redesign
removes one, that region simply keeps X's own shape while the base palette
continues to apply.

The module is Qt-free because Vivaldi receives it through Tampermonkey and the
loopback palette courier.  `twitter-userscript.py` owns the browser plumbing.
"""
from __future__ import annotations


def css(pal):
    """Return the complete X/Twitter sheet for a twelve-token palette callable."""
    p = pal
    bg, alt, border = p("bg"), p("bgAlt"), p("border")
    accent, dim, text, text_dim = p("accent"), p("dim"), p("text"), p("textDim")
    highlight, ok, warn, crit, info = (p("highlight"), p("ok"), p("warn"),
                                       p("crit"), p("info"))
    return f"""/* desktop Twitter/X — generated; do not hand-edit */
:root {{ color-scheme: dark; --desk-bg:{bg}; --desk-alt:{alt}; --desk-border:{border};
  --desk-accent:{accent}; --desk-dim:{dim}; --desk-text:{text}; --desk-muted:{text_dim};
  --desk-highlight:{highlight}; --desk-ok:{ok}; --desk-warn:{warn}; --desk-crit:{crit}; --desk-info:{info}; }}
html, body, #react-root, [data-testid="primaryColumn"], [data-testid="sidebarColumn"],
[role="main"], [role="banner"], [role="navigation"], [data-testid="BottomBar"] {{
  background-color:var(--desk-bg)!important; color:var(--desk-text)!important; }}
[data-testid="primaryColumn"], [data-testid="sidebarColumn"], [role="main"],
[data-testid="sidebarColumn"] > div {{ border-color:var(--desk-border)!important; }}
[data-testid="tweet"], [data-testid="cellInnerDiv"], [data-testid="trend"],
[data-testid="conversation"] {{ background-color:var(--desk-bg)!important; border-color:var(--desk-border)!important; }}
[data-testid="tweet"]:hover, [data-testid="cellInnerDiv"]:hover,
[role="link"]:hover, [role="menuitem"]:hover, [data-testid="UserCell"]:hover {{
  background-color:var(--desk-highlight)!important; }}
[data-testid="tweetText"], [data-testid="tweetText"] *, [data-testid="UserName"],
[data-testid="UserName"] *, [role="heading"], [data-testid="app-bar-back"] {{ color:var(--desk-text)!important; }}
[data-testid="tweetText"] a, [data-testid="UserName"] a, a[role="link"] {{ color:var(--desk-accent)!important; }}
[data-testid="tweetText"] a:hover, a[role="link"]:hover {{ color:var(--desk-info)!important; }}
[data-testid="tweetText"] span, [data-testid="UserName"] span, time,
[data-testid="socialContext"], [data-testid="app-text-transition-container"] {{ color:var(--desk-muted)!important; }}
[data-testid="tweet"] [data-testid="reply"], [data-testid="tweet"] [data-testid="retweet"],
[data-testid="tweet"] [data-testid="like"], [data-testid="tweet"] [data-testid="analytics"] {{ color:var(--desk-dim)!important; }}
[data-testid="tweet"] [data-testid="reply"]:hover {{ color:var(--desk-info)!important; }}
[data-testid="tweet"] [data-testid="retweet"]:hover {{ color:var(--desk-ok)!important; }}
[data-testid="tweet"] [data-testid="like"]:hover {{ color:var(--desk-crit)!important; }}
[data-testid="tweet"] [data-testid="analytics"]:hover {{ color:var(--desk-accent)!important; }}
[data-testid="SearchBox_Search_Input"], [data-testid="SearchBox_Search_Input"] input,
[data-testid="tweetTextarea_0"], [contenteditable="true"], input, textarea {{
  background-color:var(--desk-alt)!important; color:var(--desk-text)!important;
  border-color:var(--desk-border)!important; caret-color:var(--desk-accent)!important; }}
[data-testid="SearchBox_Search_Input"]:focus-within, [data-testid="tweetTextarea_0"]:focus-within,
[contenteditable="true"]:focus {{ outline-color:var(--desk-accent)!important; border-color:var(--desk-accent)!important; }}
[role="dialog"] > div, [data-testid="sheetDialog"], [data-testid="Dropdown"], [role="menu"] {{
  background-color:var(--desk-alt)!important; color:var(--desk-text)!important;
  border-color:var(--desk-border)!important; }}
[data-testid="tweetButton"], [data-testid="tweetButtonInline"], [data-testid="DM_Button"],
[data-testid="placementTracking"] [role="button"] {{ background-color:var(--desk-accent)!important; color:var(--desk-bg)!important; }}
[data-testid="tweetButton"] *, [data-testid="tweetButtonInline"] *, [data-testid="DM_Button"] * {{ color:var(--desk-bg)!important; }}
[aria-selected="true"] {{ color:var(--desk-accent)!important; border-color:var(--desk-accent)!important; }}
[data-testid="emptyState"] {{ background-color:var(--desk-bg)!important; color:var(--desk-muted)!important; }}
::-webkit-scrollbar-track {{ background:var(--desk-bg)!important; }}
::-webkit-scrollbar-thumb {{ background:var(--desk-border)!important; border-color:var(--desk-bg)!important; }}
::-webkit-scrollbar-thumb:hover {{ background:var(--desk-accent)!important; }}
"""
