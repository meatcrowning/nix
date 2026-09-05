"""Lossless comma-separated prompt documents.

Pills are payloads; everything around them is formatting.  Keeping those two
things separate lets the UI reorder pills without silently rewriting spaces or
paragraph breaks in the text editor.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptItem:
    id: int
    text: str


class PromptDocument:
    """A prompt as movable items in fixed, lossless formatting slots."""

    def __init__(self, prefix="", items=None, gaps=None, suffix="", next_id=0):
        self.prefix = str(prefix)
        self.items = list(items or [])
        self.gaps = list(gaps or [])
        self.suffix = str(suffix)
        self._next_id = int(next_id)
        self._check()

    @classmethod
    def parse(cls, text):
        text = str(text or "")
        cuts = _top_level_commas(text)
        starts = [0] + [at + 1 for at in cuts]
        ends = cuts + [len(text)]

        cores = []
        for start, end in zip(starts, ends):
            left = start
            while left < end and text[left].isspace():
                left += 1
            right = end
            while right > left and text[right - 1].isspace():
                right -= 1
            if left < right:
                cores.append((left, right))

        if not cores:
            return cls(prefix=text)

        items = [PromptItem(i, text[left:right])
                 for i, (left, right) in enumerate(cores)]
        gaps = [text[cores[i][1]:cores[i + 1][0]]
                for i in range(len(cores) - 1)]
        return cls(
            prefix=text[:cores[0][0]],
            items=items,
            gaps=gaps,
            suffix=text[cores[-1][1]:],
            next_id=len(items),
        )

    def serialize(self):
        if not self.items:
            return self.prefix + self.suffix
        out = [self.prefix, self.items[0].text]
        for gap, item in zip(self.gaps, self.items[1:]):
            out.extend((gap, item.text))
        out.append(self.suffix)
        return "".join(out)

    def rows(self):
        """Return UI-friendly rows without exposing mutable item objects."""
        return [
            {
                "id": item.id,
                "text": item.text,
                "breakBefore": i > 0 and ("\n" in self.gaps[i - 1]
                                             or "\r" in self.gaps[i - 1]),
            }
            for i, item in enumerate(self.items)
        ]

    def move(self, source, target):
        """Move an item to a final index, leaving every formatting slot fixed."""
        if not 0 <= source < len(self.items):
            raise IndexError(source)
        if not self.items:
            return
        target = max(0, min(int(target), len(self.items) - 1))
        item = self.items.pop(source)
        self.items.insert(target, item)

    def replace(self, item_id, text):
        """Replace one payload; separators are deliberately not editable here."""
        text = str(text)
        _require_payload(text)
        self.items[self._index_for_id(item_id)].text = text

    def remove(self, item_id):
        """Remove a pill and the separator after it (or before it when last)."""
        index = self._index_for_id(item_id)
        self.items.pop(index)
        if not self.items:
            # Removing the final semantic item means clearing the prompt.  A
            # comma-only remnant is never useful and is surprising in text mode.
            self.prefix = ""
            self.suffix = ""
            self.gaps = []
        elif index < len(self.gaps):
            self.gaps.pop(index)
        else:
            self.gaps.pop()
        self._check()

    def insert(self, index, text, separator=None):
        """Insert a new pill, copying the nearest separator style by default."""
        text = str(text)
        _require_payload(text)
        index = max(0, min(int(index), len(self.items)))
        item = PromptItem(self._next_id, text)
        self._next_id += 1

        if not self.items:
            # Preserve whitespace-only text around the first inserted payload.
            self.items.append(item)
            self._check()
            return item.id

        if separator is None:
            if index > 0 and self.gaps:
                separator = self.gaps[min(index - 1, len(self.gaps) - 1)]
            elif self.gaps:
                separator = self.gaps[0]
            else:
                separator = ", "
        separator = str(separator)
        if not _top_level_commas(separator):
            raise ValueError("a pill separator must contain a top-level comma")

        self.items.insert(index, item)
        self.gaps.insert(min(index, len(self.gaps)), separator)
        self._check()
        return item.id

    def _index_for_id(self, item_id):
        for index, item in enumerate(self.items):
            if item.id == item_id:
                return index
        raise KeyError(item_id)

    def _check(self):
        if len(self.gaps) != max(0, len(self.items) - 1):
            raise ValueError("there must be exactly one gap between each item")
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("prompt item ids must be unique")


def _require_payload(text):
    if not text or text[0].isspace() or text[-1].isspace():
        raise ValueError("a pill payload must be non-empty with no edge whitespace")
    doc = PromptDocument.parse(text)
    if (len(doc.items) != 1 or doc.prefix or doc.suffix
            or doc.items[0].text != text):
        raise ValueError("a pill payload cannot contain a top-level comma")


def _top_level_commas(text):
    """Return unescaped comma offsets outside balanced ()/[] groups."""
    cuts = []
    stack = []
    escaped = False
    pairs = {")": "(", "]": "["}
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char in "([":
            stack.append(char)
        elif char in pairs and stack and stack[-1] == pairs[char]:
            stack.pop()
        elif char == "," and not stack:
            cuts.append(index)
    return cuts
