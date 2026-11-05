"""Lifetime anchor. The host starts the server under a separate UID."""

import os
import signal
import time


def reap(*_):
    try:
        while os.waitpid(-1, os.WNOHANG)[0]:
            pass
    except ChildProcessError:
        pass


signal.signal(signal.SIGCHLD, reap)

while True:
    time.sleep(60)
