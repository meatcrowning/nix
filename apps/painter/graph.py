"""Build the ComfyUI API-format graph painter submits.

One template serves every family.  Everything that differs between models is
either a value, an optional node that gets spliced out, or a node-class swap at a
single role -- so there is no per-model workflow to keep in sync.

Nothing here ever refers to a node by its id.  Slots are addressed by the
`painter_role` recorded in each node's `_meta`, which is what lets the template be
re-authored (or exported afresh from ComfyUI) without touching this code.
"""

from __future__ import annotations

import copy
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
GRAPH_DIR = os.path.join(HERE, "graphs")


class GraphError(Exception):
    """Raised when the template and the requested operation disagree."""


class ValidationError(Exception):
    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))


def load_template(name: str) -> dict:
    path = name if os.path.isabs(name) else os.path.join(GRAPH_DIR, name)
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    return {k: v for k, v in doc.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# prompt transforms
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")

#: A DANBOORU EMOTICON keeps its underscore: `^_^`, `>_<`, `o_o`, `-_-`, `;_;`
#: are tags in their own right, and "^ ^" is not one of them. One character
#: either side of the underscore and nothing else — which is every emoticon tag
#: on the site and no real tag, since the shortest of those (`bra`, `hat`) have
#: no underscore at all.
_EMOTICON = re.compile(r"^[\w^><=+;@.|\\/*-]_[\w^><=+;@.|\\/*-]$")
#: The one family of real tags that keeps underscores: the PonyV7-style
#: aesthetic scores (`score_9`, `score_7_up`).
_SCORE = re.compile(r"^score_\d(?:_up)?$", re.I)
#: How an artist gets named when it was not written as `@name` already. Anima
#: was captioned with the `@` form, so `artist:toi8` and `by toi8` are the same
#: intent spelled the way every OTHER model wants it.
#: `by X` only when X is ONE token: "by hito_komoru" is an artist, "by the
#: window" is a sentence, and this transform must never rewrite his prose.
_ARTIST = re.compile(r"^(?:artist:\s*(.+)|by\s+([^\s,]+))$", re.I)
#: `(tag, tag:-1.0)` — a weight group. The weight is preserved verbatim; only
#: the tags inside are normalised.
_WEIGHTED = re.compile(r"^(.*?):\s*(-?\d*\.?\d+)$", re.S)


def _vocab():
    """`pylib/boorutags`, if this process can see it. Optional by design: the
    transform must still work in a checkout where only `painter/` is on the
    path (`tools/validate-graphs.py`), and a missing vocabulary means no
    canonicalisation, never an import error."""
    global _VOCAB
    if _VOCAB is _UNSET:
        try:
            import boorutags
            _VOCAB = boorutags
        except ImportError:
            _VOCAB = None
    return _VOCAB


_UNSET = object()
_VOCAB = _UNSET


def _danbooru_tag(tag: str) -> str:
    """One tag, spelled the way Anima was captioned."""
    tag = tag.strip()
    if not tag:
        return ""
    at = tag.startswith("@")
    body = tag[1:].strip() if at else tag
    m = _ARTIST.match(body)
    if m:
        at, body = True, (m.group(1) or m.group(2)).strip()
    if not (_SCORE.match(body) or _EMOTICON.match(body)):
        body = body.replace("_", " ")
    body = _WS.sub(" ", body).strip()
    # THE TAG DANBOORU ACTUALLY HAS, when what was written is a near-miss for
    # one: `one girl` -> `1girl`, `amber eyes` -> `yellow eyes` [his,
    # 2026-08-24, after a prompt went out with "one girl" in it]. A near-miss
    # is not a weaker version of the tag — it fires nothing at all. Only for
    # things that LOOK like tags (an artist handle, a sentence and a name the
    # site has never heard of are all left exactly as written), and only when
    # the vocabulary lands on something: `canonical` returns None rather than a
    # guess, because a wrong tag is worse than an unknown one.
    if body and not at and len(body.split()) <= 4 and not body.endswith("."):
        vocab = _vocab()
        if vocab is not None:
            got = vocab.canonical(body)
            if got and got["category"] in ("general", "character", "copyright",
                                           "artist"):
                name = got["tag"]
                # The canonical form gets the same underscore rule as anything
                # else, or `^_^` comes back as `^ ^`.
                body = (name if (_SCORE.match(name) or _EMOTICON.match(name))
                        else name.replace("_", " "))
                # AN ARTIST IS `@name`, and a bare handle in a prompt is one
                # the model will not recognise as an artist at all — it is the
                # single most common way an artist tag does nothing [his,
                # 2026-08-24: `artist: abe yoshitoshi, mocha` went out
                # unmarked]. The vocabulary knows which names are artists, so
                # this does not have to be guessed.
                at = at or got["category"] == "artist"
    return ("@" + body) if at and body else body


def spell_tag(tag: str) -> str:
    """One tag, spelled the way it will be SENT — public so the completer in
    `main.py` inserts what `danbooru_prompt` would have written anyway. Two
    spellings of a tag, one on screen and one on the wire, is a bug waiting for
    the day they disagree."""
    return _danbooru_tag(tag)


def _danbooru_group(text: str) -> str:
    """A comma-separated run of tags, weight suffix and all."""
    m = _WEIGHTED.match(text)
    weight = ""
    if m:
        text, weight = m.group(1), ":" + m.group(2)
    tags = [t for t in (_danbooru_tag(p) for p in text.split(",")) if t]
    return ", ".join(tags) + weight


def apply_prompt_transform(text: str, transform: str | None) -> str:
    """Anima wants one line; other families take the prompt verbatim."""
    if not text or not transform or transform == "none":
        return text
    if transform == "single_line":
        return _WS.sub(" ", text).strip()
    if transform == "danbooru":
        return danbooru_prompt(text)
    if transform == "strip":
        return text.strip()
    raise GraphError(f"unknown prompt transform {transform!r}")


def danbooru_prompt(text: str) -> str:
    """`single_line`, plus the spelling the tags were captioned with.

    Anima's vocabulary is Danbooru's, written with **spaces and not
    underscores**, and an artist is `@name` — the two things a model writing
    the prompt gets wrong most often, and both are mechanical, so they are done
    here rather than asked for [his, 2026-08-24]. Everything else is left
    exactly as written: this normalises SPELLING, it does not edit his prompt.

    Three things keep their underscores because they are not word separators:
    the `score_*` aesthetic tags, the emoticon tags (`^_^`, `>_<`), and anything
    inside a weight group is handled tag by tag with the weight untouched, so
    `(lowres, low_quality:-1.0)` comes out `(lowres, low quality:-1.0)` and
    still means what it meant.
    """
    out, buf, depth = [], [], 0

    def flush_text(chunk):
        """A run of plain tags, with whatever separated it from the group next
        to it left exactly as written — a weight group inline in a SENTENCE
        must not come back wearing commas it never had."""
        if not chunk:
            return
        m = re.match(r"^([\s,]*)(.*?)([\s,]*)$", chunk, re.S)
        core = _danbooru_group(m.group(2))
        out.append(m.group(1) + core + m.group(3) if core
                   else m.group(1) + m.group(3))

    for ch in _WS.sub(" ", text):
        if ch == "(":
            if depth == 0:
                flush_text("".join(buf))
                buf = []
            depth += 1
            buf.append(ch)
        elif ch == ")" and depth:
            buf.append(ch)
            depth -= 1
            if depth == 0:
                out.append("(" + _danbooru_group("".join(buf)[1:-1]) + ")")
                buf = []
        else:
            buf.append(ch)
    if depth:
        out.append("".join(buf))           # an unclosed group: leave it alone
    else:
        flush_text("".join(buf))
    return _WS.sub(" ", "".join(out)).strip().strip(",").strip()


# ---------------------------------------------------------------------------
# the graph
# ---------------------------------------------------------------------------


class Graph:
    def __init__(self, template: dict):
        self.nodes = copy.deepcopy(template)
        self._reindex()

    # -- role plumbing ----------------------------------------------------

    def _reindex(self):
        self.roles = {}
        for nid, node in self.nodes.items():
            role = (node.get("_meta") or {}).get("painter_role")
            if role:
                self.roles.setdefault(role, nid)

    def id_of(self, role: str) -> str:
        nid = self.roles.get(role)
        if nid is None:
            raise GraphError(f"template has no node with role {role!r}")
        return nid

    def has(self, role: str) -> bool:
        return role in self.roles

    def node(self, role: str) -> dict:
        return self.nodes[self.id_of(role)]

    def _next_id(self) -> str:
        n = 0
        for k in self.nodes:
            try:
                n = max(n, int(k))
            except ValueError:
                continue
        return str(n + 1)

    # -- edits ------------------------------------------------------------

    def set_input(self, role: str, key: str, value):
        node = self.node(role)
        node.setdefault("inputs", {})[key] = value
        return self

    def add_node(self, class_type: str, inputs: dict, role: str,
                 title: str | None = None) -> str:
        """Add a fresh node with a unique id and register its role.

        The same direct-insertion + reindex shape `insert_lora_chain` uses,
        exposed for the edit branch's extra reference images: each additional
        image is a LoadImage -> scale -> VAEEncode plus a ReferenceLatent
        spliced onto both conditioning tails. Returns the new node id.
        """
        nid = self._next_id()
        self.nodes[nid] = {
            "inputs": dict(inputs),
            "class_type": class_type,
            "_meta": {"title": title or role, "painter_role": role},
        }
        self._reindex()
        return nid

    def set_inputs(self, role: str, values: dict):
        for k, v in (values or {}).items():
            self.set_input(role, k, v)
        return self

    def set_class(self, role: str, class_type: str, inputs: dict | None = None,
                  drop: tuple = ()):
        """Swap the node class at a role, keeping its wiring.

        Used for the loader (safetensors / GGUF / int8 all expose `unet_name`
        but need different classes) and for the pixel-space latent node.
        """
        node = self.node(role)
        node["class_type"] = class_type
        for key in drop:
            node.get("inputs", {}).pop(key, None)
        if inputs:
            node.setdefault("inputs", {}).update(inputs)
        return self

    def _consumers(self, nid: str):
        """Yield (node_id, input_key, slot) for every edge out of `nid`."""
        for other_id, other in self.nodes.items():
            if other_id == nid:
                continue
            for key, val in (other.get("inputs") or {}).items():
                if isinstance(val, list) and len(val) == 2 and val[0] == nid:
                    yield other_id, key, val[1]

    def remove(self, role: str):
        """Splice a node out, reconnecting its consumers to its own upstreams.

        `painter_bypass` says which input stands in for which output -- the same
        rule ComfyUI's own bypass uses.  NegPip is the interesting case: it has
        two outputs, so removing it must send the positive encode back to the raw
        CLIP while the model path returns to the loader.
        """
        if not self.has(role):
            return self
        nid = self.id_of(role)
        node = self.nodes[nid]
        meta = node.get("_meta") or {}
        bypass = {str(k): v for k, v in (meta.get("painter_bypass") or {}).items()}
        if not bypass:
            raise GraphError(f"role {role!r} has no painter_bypass and cannot be removed")

        replacements = {}
        for out_slot, in_key in bypass.items():
            src = (node.get("inputs") or {}).get(in_key)
            if not (isinstance(src, list) and len(src) == 2):
                raise GraphError(
                    f"role {role!r} bypass output {out_slot} -> input {in_key!r} is not a link"
                )
            replacements[int(out_slot)] = src

        for other_id, key, slot in list(self._consumers(nid)):
            if slot not in replacements:
                raise GraphError(
                    f"cannot remove {role!r}: output {slot} is consumed by "
                    f"{other_id}.{key} but has no bypass"
                )
            self.nodes[other_id]["inputs"][key] = list(replacements[slot])

        del self.nodes[nid]
        self._reindex()
        return self

    def drop(self, role: str):
        """Delete a node outright, refusing if anything still reads it.

        `remove()` splices a node OUT of a chain and needs `painter_bypass` to
        say what replaces it.  A source node (LoadImage) has no input standing
        in for its output: text-to-video simply does not have one, so its
        consumers are rewired to plain values first and this asserts that they
        were -- a dangling link is a submit-time error from ComfyUI with a node
        id in it, which is the failure this class exists to prevent.
        """
        if not self.has(role):
            return self
        nid = self.id_of(role)
        left = [f"{oid}.{key}" for oid, key, _ in self._consumers(nid)]
        if left:
            raise GraphError(f"cannot drop {role!r}: still read by {', '.join(left)}")
        del self.nodes[nid]
        self._reindex()
        return self

    def retarget(self, old, new, skip=()):
        """Point every consumer of link `old` at `new`."""
        old = list(old)
        for nid, node in self.nodes.items():
            if nid in skip:
                continue
            for key, val in (node.get("inputs") or {}).items():
                if isinstance(val, list) and len(val) == 2 and list(val) == old:
                    node["inputs"][key] = list(new)
        return self

    def insert_lora_chain(self, loras, model_src, clip_src=None):
        """Chain LoRA loaders onto the MODEL (and CLIP, if one patches it).

        Returns the (model, clip) links the rest of the graph should now read.
        Order is preserved because chain order changes the result.
        """
        model_tail = list(model_src)
        clip_tail = list(clip_src) if clip_src else None
        added = []
        for i, lora in enumerate(loras):
            nid = self._next_id()
            patches_clip = bool(lora.get("patches_clip")) and clip_tail is not None
            inputs = {
                "lora_name": lora["name"],
                "strength_model": float(lora.get("strength", 1.0)),
                "model": list(model_tail),
            }
            cls = "LoraLoaderModelOnly"
            if patches_clip:
                cls = "LoraLoader"
                inputs["clip"] = list(clip_tail)
                inputs["strength_clip"] = float(
                    lora.get("strength_clip", lora.get("strength", 1.0))
                )
            self.nodes[nid] = {
                "inputs": inputs,
                "class_type": cls,
                "_meta": {"title": f"LoRA {i + 1}", "painter_role": f"lora{i}"},
            }
            added.append(nid)
            model_tail = [nid, 0]
            if patches_clip:
                clip_tail = [nid, 1]
        if added:
            self._reindex()
            # Everything that read the original sources now reads the chain tail.
            self.retarget(model_src, model_tail, skip=set(added))
            if clip_src and clip_tail != list(clip_src):
                self.retarget(clip_src, clip_tail, skip=set(added))
        return model_tail, clip_tail

    # -- output -----------------------------------------------------------

    def to_prompt(self, strip_meta: bool = False) -> dict:
        out = {}
        for nid, node in self.nodes.items():
            n = {"inputs": copy.deepcopy(node.get("inputs", {})),
                 "class_type": node["class_type"]}
            if not strip_meta:
                n["_meta"] = copy.deepcopy(node.get("_meta", {}))
            out[nid] = n
        return out


# ---------------------------------------------------------------------------
# validation against a live /object_info
# ---------------------------------------------------------------------------


def input_spec(object_info: dict, class_type: str, key: str):
    node = object_info.get(class_type)
    if not node:
        return None
    inp = node.get("input") or {}
    for section in ("required", "optional"):
        spec = (inp.get(section) or {}).get(key)
        if spec is not None:
            return spec
    return None


def enum_values(object_info: dict, class_type: str, key: str):
    """Combo options, tolerating all three /object_info shapes.

    Older nodes give `[[a, b, c], {...}]`; newer ones give `["COMBO", {"options":
    [...]}]`; a DynamicCombo (SaveVideo's `codec`) gives that same list with each
    option a `{"key": ..., "inputs": {...}}` DICT, and the value a graph carries
    is the key alone.  Reading those literally made every video graph fail
    validation on a `codec` the backend accepts.
    """
    spec = input_spec(object_info, class_type, key)
    if not spec:
        return None
    head = spec[0]
    if isinstance(head, list):
        vals = head
    else:
        opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
        vals = opts.get("options")
    if not isinstance(vals, list):
        return None
    return [v.get("key") if isinstance(v, dict) else v for v in vals]


# Enums that are a LIVE DIRECTORY LISTING rather than a node contract. The file
# painter uploads for image-to-video lands in ComfyUI's input directory a moment
# before the graph is submitted, so it cannot be in the /object_info fetched at
# startup — validating against that list rejects the one graph that is certainly
# correct. Model names are deliberately NOT in here: those really are a contract,
# and a missing weight file should fail before it reaches the backend.
LIVE_ENUMS = {("LoadImage", "image"), ("LoadImageMask", "image")}


def validate(prompt: dict, object_info: dict, check_enums: bool = True):
    """Return a list of human-readable problems; empty means the graph will run."""
    problems = []
    for nid, node in prompt.items():
        cls = node.get("class_type")
        role = (node.get("_meta") or {}).get("painter_role", nid)
        if cls not in object_info:
            problems.append(f"{role}: node class {cls!r} is not installed")
            continue
        spec = object_info[cls].get("input") or {}
        known = set(spec.get("required") or {}) | set(spec.get("optional") or {})
        for key, val in (node.get("inputs") or {}).items():
            if key not in known:
                problems.append(f"{role} ({cls}): no input named {key!r}")
                continue
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str):
                if val[0] not in prompt:
                    problems.append(f"{role} ({cls}): {key} links to missing node {val[0]}")
                continue
            if check_enums and isinstance(val, str) and (cls, key) not in LIVE_ENUMS:
                allowed = enum_values(object_info, cls, key)
                if allowed is not None and val not in allowed:
                    sample = ", ".join(map(str, allowed[:6]))
                    problems.append(
                        f"{role} ({cls}): {key}={val!r} is not one of [{sample}...]"
                    )
        for key in spec.get("required") or {}:
            if key not in (node.get("inputs") or {}):
                problems.append(f"{role} ({cls}): required input {key!r} is unset")
    return problems


def fetch_object_info(url: str = "http://127.0.0.1:8188", timeout: float = 30.0) -> dict:
    import urllib.request

    with urllib.request.urlopen(f"{url}/object_info", timeout=timeout) as resp:
        return json.load(resp)
