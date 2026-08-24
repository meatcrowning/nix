"""His generation shorthand — `anima. 2:3 x1 1girl, solo, …` — as parsed args.

He does not want to describe a picture to a model and hope it picks the right
knobs; he wants to TYPE the job. So a message that opens with a model or a mode
word is read here, deterministically, into the exact arguments `make_image` /
`make_video` take, and the model is handed those arguments rather than left to
infer them from prose. Two things follow from that, and they are the whole
design:

* **The numbers are never the model's guess.** Aspect, pixel budget, count,
  seconds and seed are parsed by the code below, so "2:3" cannot come back 3:2.
* **The prompt is never rewritten.** Everything after the settings is his text
  verbatim, danbooru tag lists included — a local model asked to "improve" a tag
  list will, and that is not what he asked for.

The parse is CONSERVATIVE: a message that does not open with one of these words
is not shorthand, and a token that is not recognised ends the settings and
begins the prompt. Nothing here can fire on ordinary chat.

    anima. 2:3 x1 1girl, solo, looking at viewer
    krea. 16:9 x2 a lighthouse in fog, long lens
    klein. make it night          (with a picture attached -> an edit)
    video. first frame: [image]. 6s i2v. she turns to the camera
"""

from __future__ import annotations

import re

#: The word he opens with -> what it means. A MODEL name selects the model and
#: leaves the kind alone; a MODE word (video/edit/image) selects the kind. They
#: are one table because he types them in one slot.
HEADS = {
    "anima": {"model": "anima"}, "anime": {"model": "anima"},
    "krea": {"model": "krea"}, "real": {"model": "krea"},
    "klein": {"model": "klein", "kind": "edit"},
    "flux": {"model": "klein", "kind": "edit"},
    "edit": {"kind": "edit"},
    "chroma": {"model": "chroma"},
    "qwen": {"model": "qwen"},
    "sdxl": {"model": "miruku"},
    "lumina": {"model": "lumina"},
    "zimage": {"model": "z_image"}, "z_image": {"model": "z_image"},
    "z-image": {"model": "z_image"},
    "minimax": {"model": "minimax", "kind": "video"},
    "video": {"kind": "video"}, "vid": {"kind": "video"},
    "image": {"kind": "image"}, "img": {"kind": "image"},
    "pic": {"kind": "image"},
}

#: The i2v/t2v family of words: which ends of a clip he means to pin.
CLIP_MODES = {
    "t2v": (0, False), "t2va": (0, False),
    "i2v": (1, False), "i2va": (1, False),
    "fl2v": (1, True), "fl2va": (1, True),
    "l2v": (0, True), "l2va": (0, True),
}

_HEAD = re.compile(r"^\s*([A-Za-z][\w\-]*)\s*[.:]\s*")
_ASPECT = re.compile(r"^(\d{1,2}):(\d{1,2})$")
_MP = re.compile(r"^x(\d+(?:\.\d+)?)(?:mp)?$", re.I)
_MP2 = re.compile(r"^(\d+(?:\.\d+)?)mp$", re.I)
_COUNT = re.compile(r"^(\d{1,2})x$", re.I)
_SECONDS = re.compile(r"^(\d+(?:\.\d+)?)s(?:ec|ecs|econds)?$", re.I)
_KEYNUM = re.compile(r"^(seed|steps)[:=](\d+)$", re.I)
#: `first frame: …` / `last frame: …` — a LABEL, not a path. What he pastes
#: there is a picture, and the picture arrives as an attachment, so the label's
#: own text ("[pasted image]") is discarded and the attachment used in its place.
_FRAME = re.compile(r"^(first|last)\s+frame\s*[:=]\s*([^.]*)\.?\s*", re.I)


def parse(text, images=None):
    """`text` -> `{"tool": …, "args": {…}}`, or None if it is not shorthand.

    `images` are the local paths of the pictures attached to this message, in
    the order he attached them; they fill the frames of a clip and the subject
    of an edit, because that is what attaching one to a generation MEANS.
    """
    images = [p for p in (images or []) if p]
    m = _HEAD.match(text or "")
    if not m:
        return None
    head = HEADS.get(m.group(1).lower())
    if head is None:
        return None
    kind = head.get("kind") or "image"
    args = {}
    if head.get("model"):
        args["model"] = head["model"]
    rest = text[m.end():]
    want_first = want_last = False

    while rest:
        fm = _FRAME.match(rest)
        if fm:
            kind = "video" if kind != "edit" else kind
            if fm.group(1).lower() == "first":
                want_first = True
            else:
                want_last = True
            rest = rest[fm.end():]
            continue
        tok = rest.split(None, 1)
        if not tok:
            break
        word, tail = tok[0], (tok[1] if len(tok) > 1 else "")
        bare = word.rstrip(".,")
        low = bare.lower()
        if _ASPECT.match(bare):
            args["aspect"] = bare
        elif _MP.match(bare):
            args["megapixels"] = float(_MP.match(bare).group(1))
        elif _MP2.match(bare):
            args["megapixels"] = float(_MP2.match(bare).group(1))
        elif _COUNT.match(bare):
            args["count"] = int(_COUNT.match(bare).group(1))
        elif _SECONDS.match(bare):
            args["seconds"] = float(_SECONDS.match(bare).group(1))
            kind = "video"
        elif _KEYNUM.match(bare):
            k, v = _KEYNUM.match(bare).groups()
            args[k.lower()] = int(v)
        elif low in CLIP_MODES:
            kind = "video"
            firsts, lasts = CLIP_MODES[low]
            want_first = want_first or bool(firsts)
            want_last = want_last or lasts
        else:
            break                      # not a setting: the prompt starts here
        rest = tail

    args["prompt"] = rest.strip()
    if not args["prompt"] and not images:
        return None

    if kind == "video":
        pool = list(images)
        if not want_first and not want_last and pool:
            want_first = True          # a picture on a clip is its first frame
        if want_first and pool:
            args["first_frame"] = pool.pop(0)
        if want_last and pool:
            args["last_frame"] = pool.pop(0)
        args.pop("count", None)
        return {"tool": "make_video", "args": args}

    if kind == "edit" or (images and kind == "image"):
        if not images:
            return None                # "edit" with nothing to edit is not a job
        args["input_images"] = list(images)
        args.pop("aspect", None)       # the picture decides an edit's size
        args.pop("count", None)
        return {"tool": "make_image", "args": args}

    return {"tool": "make_image", "args": args}


def hint(text, images=None):
    """`parse` + `hint_for`, for a caller that wants only the block."""
    got = parse(text, images)
    return hint_for(got) if got else ""


def hint_for(got):
    """The block appended to his message when it parses as shorthand.

    It is an INSTRUCTION with the arguments already in it, not a description of
    what he typed: the model's only job is to make the call. Written as one
    block so the turn he sees is still his own sentence (oracle's `send` puts
    this after the prompt, like the attachment notes)."""
    if not got:
        return ""
    import json
    return ("[He typed a generation shorthand, already parsed for you. Call "
            "%s ONCE, with exactly these arguments and nothing added or "
            "reworded:\n%s\nThe prompt is his own text — pass it through "
            "verbatim. Do not call any other tool first, and do not ask him to "
            "confirm.]" % (got["tool"], json.dumps(got["args"], indent=1)))
