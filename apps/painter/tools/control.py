#!/usr/bin/env python3
"""Inspect or populate an already-running Painter. Never starts a GUI/backend."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_control import discover, request, target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', help='window socket from list (required when multiple windows are open)')
    commands = parser.add_subparsers(dest='op', required=True)
    for name in ('list', 'state', 'describe', 'generate'):
        commands.add_parser(name)
    select = commands.add_parser('select')
    choice = select.add_mutually_exclusive_group(required=True)
    choice.add_argument('--model')
    choice.add_argument('--mode')
    apply = commands.add_parser('apply', help='apply a JSON object containing settings and/or image paths/LoRAs')
    apply.add_argument('file', help='JSON file, or - for stdin')
    args = parser.parse_args()
    try:
        if args.op == 'list':
            result = discover()
        else:
            path = target(args.socket)
            payload = dict(op=args.op)
            if args.op == 'select':
                payload.update({key: getattr(args, key) for key in ('model', 'mode') if getattr(args, key) is not None})
            if args.op == 'apply':
                data = sys.stdin.read() if args.file == '-' else Path(args.file).read_text()
                body = json.loads(data)
                if not isinstance(body, dict) or 'op' in body:
                    raise ValueError('Apply expects an object without an op field')
                payload.update(body)
            if args.op in ('apply', 'generate') and 'model' not in payload:
                payload['model'] = request(path, {'op': 'state'})['model']
            result = request(path, payload)
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps(dict(ok=False, error=str(exc))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
