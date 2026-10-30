"""Frozen generation inputs and per-submission lifecycle, shared by frontends."""
from __future__ import annotations

from dataclasses import dataclass, field
import copy
import secrets
import time
import uuid

import wildcards


@dataclass
class Submission:
    params: dict
    entry: object
    registry: object
    object_info: dict | None
    count: int = 1
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "preparing"
    cancelled: bool = False
    pending_jobs: int = 0
    pending_saves: int = 0
    saved: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)
    reservation_released: bool = False

    @classmethod
    def freeze(cls, params, entry, registry, object_info, count, loras, last_seed):
        values = copy.deepcopy(params)
        values["loras"] = copy.deepcopy(loras)
        if values.get("reuseSeed") and last_seed >= 0:
            values["seed"] = last_seed
            values["randomSeed"] = False
        values.pop("reuseSeed", None)
        # Freeze model assignments as well as the form: rescanning or changing
        # the model during an upload cannot change the submitted graph.
        return cls(values, copy.deepcopy(entry), copy.deepcopy(registry),
                   copy.deepcopy(object_info), max(1, min(100, int(count))))

    def cancel(self):
        self.cancelled = True
        self.state = "cancelled"


def build_job(registry, entry, params, object_info=None):
    """Expand the concrete seed's conditioning and retain lossless input text."""
    from moss_layout import import_prompt
    p = copy.deepcopy(params)
    if (registry.family_of(entry) or {}).get("id") == "moss_image":
        p = import_prompt(p)
    raw_boxes = {"positive": p.get("positive", ""), "negative": p.get("negative", "")}
    raw_layout = copy.deepcopy(p.get("moss_layout"))
    options = p.get("wildcard_options")
    positive, negative = wildcards.expand_prompts(
        raw_boxes["positive"], raw_boxes["negative"], p["seed"], options=options)
    p["positive"] = positive
    if "negative" in p:
        p["negative"] = negative
    if raw_layout:
        p["moss_layout"] = wildcards.expand_layout(raw_layout, p["seed"], options=options)
    built = registry.build(entry, p, object_info=object_info)
    built["params"]["prompt_boxes"] = raw_boxes
    if options is not None:
        built["params"]["wildcard_options"] = copy.deepcopy(options)
    if raw_layout:
        built["params"]["moss_layout"] = raw_layout
    return built


def build_batch(submission):
    """Validate the entire batch before allowing its first network submission."""
    base = copy.deepcopy(submission.params)
    seed = int(base.get("seed", 0))
    randomise = bool(base.pop("randomSeed", False)) or seed < 0
    base.pop("reuseSeed", None)
    result = []
    for n in range(submission.count):
        p = dict(base, seed=secrets.randbelow(2**50) if randomise else seed + n)
        result.append(build_job(submission.registry, submission.entry, p, submission.object_info))
    return result
