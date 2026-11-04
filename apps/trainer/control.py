"""Cooperative controls, consumed only at completed optimizer steps."""
import json
import threading


class Controls:
    def __init__(self):
        self.condition = threading.Condition()
        self.paused = False
        self.stopping = False
        self.save = False

    def submit(self, command):
        with self.condition:
            if command == 'pause':
                self.paused = True
            elif command == 'resume':
                self.paused = False
            elif command == 'stop':
                self.stopping = True
                self.paused = False
            elif command == 'save':
                self.save = True
            self.condition.notify_all()

    def read(self, stream):
        for line in stream:
            try:
                self.submit(json.loads(line)['command'])
            except (ValueError, KeyError, TypeError):
                pass
        # Closing/crashing the UI requests a recoverable stop, never orphans
        # an unobserved training process on the GPU.
        self.submit('stop')

    def boundary(self, save, emit):
        announced = False
        while True:
            with self.condition:
                stop, saving, paused = self.stopping, self.save, self.paused
                self.save = False
            if stop:
                save()
                return False
            if saving:
                save()
                emit('paused' if paused else 'training')
            if not paused:
                if announced:
                    emit('training')
                return True
            if not announced:
                emit('paused')
                announced = True
            with self.condition:
                self.condition.wait(timeout=0.25)
