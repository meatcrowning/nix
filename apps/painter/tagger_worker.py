"""One bounded CPU-only inference; stdout is a single JSON result."""
import codecs
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import selectors
import signal
import subprocess
import sys
import time


class Tags:
    def __init__(self, count):
        self.count, self.pending, self.items, self.seen = count, '', [], set()

    def feed(self, text):
        self.pending += text
        # llama-completion emits this marker only for EOS, not token exhaustion.
        if '[end of text]' in self.pending:
            self.pending = self.pending.split('[end of text]', 1)[0] + ','
        while ',' in self.pending and len(self.items) < self.count:
            value, self.pending = self.pending.split(',', 1)
            value = ' '.join(value.strip(' \r\n\t\"').split())
            # Output is descriptive phrases, never prose, markup or a numbered list.
            if not value or len(value) > 100 or any(c in value for c in '<>[]:'):
                continue
            value = re.sub(r'^\d+[.)]\s*', '', value).strip()
            key = value.casefold()
            if value and key not in self.seen:
                self.items.append(value)
                self.seen.add(key)
        return len(self.items) == self.count


class Prompt:
    def __init__(self):
        self.text = ''

    def feed(self, text):
        self.text += text
        return '[end of text]' in self.text

    def finish(self):
        complete = '[end of text]' in self.text
        text = self.text.split('[end of text]', 1)[0].strip()
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1].strip()
        if not text or any(marker in text for marker in ('<think', '</think', '<|')):
            raise ValueError('The model did not return a usable prompt. Try again.')
        if not complete:
            # A hard token cap may split a word. Keep only complete sentences.
            ends = list(re.finditer(r'[.!?](?:["”’]?(?=\s|$))', text))
            if not ends:
                raise ValueError('No complete sentence fit the token limit. Increase it and try again.')
            text = text[:ends[-1].end()].strip()
        return text


def child_limits():
    # This subprocess is deliberately outside the GPU backend warden: it neither
    # loads GPU layers nor releases another client's ComfyUI/Ollama lease.
    parent = os.getppid()
    ctypes.CDLL(None).prctl(1, signal.SIGKILL)
    if os.getppid() != parent or parent == 1:
        os._exit(1)
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    os.nice(5)


def generate(request, binary=None, model=None, timeout=90):
    prose = request.get('task', 'tags') == 'prompt'
    tokens = int(request.get('tokens', 128))
    if prose and not 16 <= tokens <= 512:
        raise ValueError('Choose between 16 and 512 output tokens.')
    count = int(request.get('count', 6))
    if not 1 <= count <= 32:
        raise ValueError('Choose between 1 and 32 tags.')
    caption = str(request.get('caption', '')).strip()[:2000]
    if not caption and not (prose and (request.get('scene') or request.get('tags'))):
        raise ValueError('Write a region prompt first.')
    binary = binary or os.environ.get('PAINTER_TAG_LLAMA', '')
    model = model or os.environ.get('PAINTER_TAG_MODEL', '')
    if not Path(binary).is_file() or not Path(model).is_file():
        raise ValueError('Local tag model is unavailable. Relaunch Painter after rebuilding.')
    available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    if available < 4 * 1024**3:
        raise ValueError('Local writing needs at least 4 GiB of available RAM.')
    system = ('Extract concise visual tags for an image region. Output only distinct descriptive '
              'phrases separated by commas. Include a comma after EVERY tag, including the last. '
              'No introduction, explanation, numbering, reasoning or markup. Describe only what '
              'is supported by the region description; use the scene for context. '
              'Return %d tags.' % count)
    context = dict(region=caption, scene=str(request.get('scene', ''))[:1500])
    if prose:
        system = ('Write a concise visual description for one region of an image. Polish or expand '
                  'the existing region prompt, using the scene, tags, region type and palette as '
                  'context. Preserve the subject and requested details. Describe only this region, '
                  'not the entire scene. Respect its palette and exact wording; do not invent extra '
                  'lettering. Return only the description, in complete sentences, with no heading, '
                  'explanation, reasoning or markup. Finish within about %d words.' % max(6, tokens // 2))
        context.update(kind=str(request.get('kind', 'object'))[:30],
                       tags=[str(v)[:100] for v in request.get('tags', [])[:16]],
                       palette=[str(v)[:50] for v in request.get('palette', [])[:12]],
                       wording=str(request.get('wording', ''))[:300])
    context = json.dumps(context, ensure_ascii=False)
    # The pinned LFM GGUF uses ChatML. Supplying the completed empty thinking
    # block starts directly in its final answer instead of spending the budget
    # on reasoning. llama adds the model's BOS token itself.
    prompt = '<|im_start|>system\n%s<|im_end|>\n<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n<think></think>\n' % (system, context)
    args = [binary, '-m', model, '-ngl', '0', '-t', '4', '-tb', '4', '-c', '4096' if prose else '2048',
            '-n', str(tokens if prose else min(1024, count * 24 + 96)), '--temp', '0.3', '--no-warmup',
            '--no-conversation', '--no-display-prompt', '--simple-io',
            '--color', 'off', '--no-escape', '-p', prompt]
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, preexec_fn=child_limits)
    parser = Prompt() if prose else Tags(count)
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    deadline = time.monotonic() + timeout
    seen = 0
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            selector.register(proc.stderr, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise ValueError('Local writing timed out. Try a smaller output limit or a shorter prompt.')
                for key, _ in selector.select(min(.2, max(0, deadline - time.monotonic()))):
                    data = os.read(key.fileobj.fileno(), 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    if key.fileobj is proc.stderr:
                        continue
                    seen += len(data)
                    if seen > 16384:
                        raise ValueError('Local tagger exceeded its output limit.')
                    if parser.feed(decoder.decode(data)):
                        return parser.finish() if prose else parser.items
        proc.wait(timeout=1)
        if proc.returncode:
            raise ValueError('Local tag model failed to run (exit %s).' % proc.returncode)
        if prose:
            return parser.finish()
        # Only delimiters complete tags; a token limit can leave a partial word.
        raise ValueError('Model produced only %d of %d complete, distinct tags. Try again.' % (len(parser.items), count))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def main():
    def cancelled(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, cancelled)
    lock = None
    try:
        root = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp'))
        lock = os.open(str(root / ('painter-tags-%d.lock' % os.getuid())), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another Painter window is using the local writer. Try again shortly.')
        request = json.loads(sys.stdin.buffer.readline(16384))
        value = generate(request)
        result = dict(prompt=value, error='') if request.get('task') == 'prompt' else dict(tags=value, error='')
    except Exception as exc:
        result = dict(tags=[], error=str(exc))
    finally:
        if lock is not None:
            os.close(lock)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
