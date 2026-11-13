"""Shared, Qt-free vocabulary for Coder's two backends.

A backend is a protocol state machine. It never owns a process: the Qt layer
(session.py) runs the CLI, hands every stdout line to ``on_line()`` and gives
the backend a ``write(line)`` callable for stdin. Tests drive the same objects
with ``fake.py``'s fixture replayer, so the parsing seen in a harness is the
parsing the window runs.

Backends report through ``sink(event, payload)``. Events:

  session     {"native_id", "model", "cwd", "mode"}       the CLI's own ids
  caps        {"models": [...], "commands": [...]}        pickers/completion
  item        {"id", "kind", ...}                         create or replace
  item_patch  {"id", <fields>..., "meta_patch"?}            update some fields
  delta       {"id", "field", "text"}                     append to a field
  state       {"state"}                                   STATES below
  turn        {"status", "error", "usage"}                a turn finished
  usage       {"used", "window", "cost"}                  context meter
  limits      {"label", "used_percent", "resets_at"}      account window
  title       {"title"}
  error       {"message"}
  diff        {"turn", "diff"}                            whole-turn diff

Item kinds: user, assistant, reasoning, tool, command, file_change, plan,
approval, error, notice, image. Every item carries ``id`` and ``kind``; the
other keys are listed with ``new_item``.
"""

STATES = ("idle", "starting", "running", "waiting", "interrupted", "failed",
          "exited")


def new_item(item_id, kind, **kw):
    item = {
        "id": str(item_id),
        "kind": kind,
        "text": "",          # prose: message, reasoning, output, plan
        "title": "",         # one-line label: tool name, command, path
        "detail": "",        # secondary text: input, cwd, exit code
        "status": "",        # running/completed/failed/declined/waiting
        "meta": {},          # backend-specific extras (approval options...)
    }
    item.update(kw)
    return item


def short(text, n=160):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 3] + "..."


class Backend:
    """Common surface; concrete classes fill the protocol in."""

    name = ""

    def __init__(self, sink, write):
        self.sink = sink
        self.write = write
        self.native_id = ""
        self.state = "idle"

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.sink("state", {"state": state})

    # Overridden per backend.
    def start(self):
        pass

    def send(self, text, images=()):
        raise NotImplementedError

    def interrupt(self):
        pass

    def answer(self, request_id, decision, note=""):
        pass

    def set_mode(self, mode):
        pass

    def set_model(self, model):
        pass

    def on_line(self, line):
        raise NotImplementedError

    def on_exit(self, code, stderr=""):
        tail = " ".join(str(stderr or "").split())[-400:]
        if self.state not in ("exited",):
            if code not in (0, None) and tail:
                self.sink("error", {"message": "%s exited %s: %s" % (self.name, code, tail)})
            self.set_state("exited")
