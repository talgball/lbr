"""
Probe script for de-risking wake-word fast-stop plan.

Two probes:
  1. Does engine.stop() actually cut a long utterance mid-speech?
  2. What is the audible gap when splitting one utterance into two
     sentence-level say()/runAndWait() calls?

Run from a terminal where audio works (local console or tmux session
started from a terminal that has audio).

    python tests/probe_pyttsx3.py stop         # probe 1
    python tests/probe_pyttsx3.py gap          # probe 2
    python tests/probe_pyttsx3.py both         # both
"""

import sys
import time
import threading

import pyttsx3


LONG_TEXT = (
    "This is a long sentence designed to take several seconds to speak, "
    "so that we have time to observe whether the engine stop call "
    "interrupts speech mid utterance or waits until the sentence has "
    "completed naturally on its own."
)

TWO_SENTENCES = [
    "This is the first sentence.",
    "And this is the second sentence right after it.",
]

ONE_UTTERANCE = "This is the first sentence. And this is the second sentence right after it."


def probe_stop():
    """Start speaking a long sentence; call engine.stop() after 1.5s."""
    print("\n=== Probe 1: engine.stop() during utterance ===")
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)

    def stopper():
        time.sleep(1.5)
        t_stop = time.perf_counter()
        print("  [%.3f] calling engine.stop()" % (t_stop - t0))
        engine.stop()
        print("  [%.3f] engine.stop() returned" % (time.perf_counter() - t0))

    engine.say(LONG_TEXT)
    print("  Expected audible speech duration if uninterrupted: ~10s")
    print("  Will call engine.stop() at t=1.5s")

    t0 = time.perf_counter()
    threading.Thread(target=stopper, daemon=True).start()
    engine.runAndWait()
    t_done = time.perf_counter()
    print("  [%.3f] runAndWait() returned" % (t_done - t0))
    print("  Result: if audible speech stopped near 1.5s, stop() works.")
    print("          if full sentence played to end (~10s), stop() is ignored.")


def probe_gap_split():
    """Speak two sentences as two separate runAndWait() calls."""
    print("\n=== Probe 2a: two sentences, two runAndWait() calls ===")
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)

    t0 = time.perf_counter()
    engine.say(TWO_SENTENCES[0])
    engine.runAndWait()
    t1 = time.perf_counter()
    gap_start = t1

    engine.say(TWO_SENTENCES[1])
    t_between = time.perf_counter()
    engine.runAndWait()
    t2 = time.perf_counter()

    print("  First sentence total: %.3fs" % (t1 - t0))
    print("  Gap (between runAndWait return and next say start): %.3fs"
          % (t_between - gap_start))
    print("  Second sentence total: %.3fs" % (t2 - t_between))
    print("  End-to-end: %.3fs" % (t2 - t0))
    print("  Listen for a pause between sentences. "
          "If it sounds like a normal sentence break, we're fine.")


def probe_gap_single():
    """Speak the same content as one runAndWait() call for comparison."""
    print("\n=== Probe 2b: same content as single runAndWait() call ===")
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)

    t0 = time.perf_counter()
    engine.say(ONE_UTTERANCE)
    engine.runAndWait()
    t1 = time.perf_counter()
    print("  Single-utterance total: %.3fs" % (t1 - t0))
    print("  Compare the natural sentence break here vs the split version.")


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'both'

    if mode in ('stop', 'both'):
        probe_stop()
        time.sleep(0.5)

    if mode in ('gap', 'both'):
        probe_gap_split()
        time.sleep(0.5)
        probe_gap_single()

    print("\nDone.")
