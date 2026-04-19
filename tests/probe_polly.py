"""
Probe script for de-risking wake-word fast-stop plan (Polly backend).

The runtime uses SPEECH_SERVICE='aws_polly' (robttspolly.py), which
synthesizes via Polly and plays via pydub.playback.play → ffplay.

Probes:
  A. Inter-chunk gap: call play() twice on two pre-synthesized sentences
     vs once on their concatenation. Measures ffplay spawn overhead.
  B. Abort: can we SIGTERM the ffplay subprocess to cut speech mid-sentence?

Requires ROBOT_AWS_AK and ROBOT_AWS_SK in env.

Usage:
    python tests/probe_polly.py gap
    python tests/probe_polly.py abort
    python tests/probe_polly.py both
"""

import sys
import os
import time
import io
import signal
import subprocess
import threading

import boto3
from pydub import AudioSegment
from pydub.playback import play


LONG_SENTENCE = (
    "This is a long sentence designed to take several seconds to speak, "
    "so that we have time to observe whether we can abort the current "
    "utterance mid speech or have to wait for it to complete."
)

S1 = "This is the first sentence."
S2 = "And this is the second sentence right after it."
COMBINED = S1 + " " + S2


def polly_client():
    return boto3.Session(
        aws_access_key_id=os.environ['ROBOT_AWS_AK'],
        aws_secret_access_key=os.environ['ROBOT_AWS_SK'],
        region_name='us-west-2',
    ).client('polly')


def synth(client, text, voice_id='Kevin'):
    r = client.synthesize_speech(
        Engine='neural', Text=text, OutputFormat='mp3', VoiceId=voice_id,
    )
    buf = io.BytesIO(r['AudioStream'].read())
    return AudioSegment.from_file(buf, format='mp3')


def probe_gap():
    print("\n=== Probe A: inter-chunk gap with pydub.play ===")
    client = polly_client()

    t_syn0 = time.perf_counter()
    seg1 = synth(client, S1)
    seg2 = synth(client, S2)
    seg_both = synth(client, COMBINED)
    t_syn1 = time.perf_counter()
    print("  Synthesized 3 clips in %.2fs" % (t_syn1 - t_syn0))

    print("\n  -- Split version (two play() calls) --")
    t0 = time.perf_counter()
    play(seg1)
    t1 = time.perf_counter()
    gap_start = t1
    play(seg2)
    t2 = time.perf_counter()
    print("    Sentence 1 play() duration: %.3fs (audio len %.3fs)"
          % (t1 - t0, seg1.duration_seconds))
    print("    Sentence 2 play() duration: %.3fs (audio len %.3fs)"
          % (t2 - gap_start, seg2.duration_seconds))
    print("    Total split: %.3fs" % (t2 - t0))

    time.sleep(0.8)
    print("\n  -- Single version (one play() call on combined audio) --")
    t3 = time.perf_counter()
    play(seg_both)
    t4 = time.perf_counter()
    print("    Combined play() duration: %.3fs (audio len %.3fs)"
          % (t4 - t3, seg_both.duration_seconds))

    overhead_split = (t2 - t0) - (seg1.duration_seconds + seg2.duration_seconds)
    overhead_single = (t4 - t3) - seg_both.duration_seconds
    extra_gap = overhead_split - overhead_single
    print("\n  Split overhead vs audio length:  %+.3fs" % overhead_split)
    print("  Single overhead vs audio length: %+.3fs" % overhead_single)
    print("  Inter-chunk gap attributable to ffplay re-spawn: %+.3fs"
          % extra_gap)
    print("  If extra_gap < 0.1s, sentence-chunking sounds natural.")
    print("  If extra_gap > 0.3s, we need pre-synth + single-stream path.")


def probe_abort():
    """Reimplement pydub.play inline so we can capture the ffplay PID
    and SIGTERM it mid-utterance."""
    print("\n=== Probe B: abort in-flight utterance via SIGTERM on ffplay ===")
    client = polly_client()
    seg = synth(client, LONG_SENTENCE)
    print("  Audio length: %.2fs" % seg.duration_seconds)

    # Write to a temp wav and invoke ffplay ourselves (mirrors pydub's behavior)
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        seg.export(f.name, format='wav')
        wav_path = f.name

    try:
        print("  Spawning ffplay; will SIGTERM at t=1.5s")
        t0 = time.perf_counter()
        proc = subprocess.Popen(
            ['ffplay', '-nodisp', '-autoexit', '-hide_banner',
             '-loglevel', 'error', wav_path],
            stdin=subprocess.DEVNULL,
        )

        def killer():
            time.sleep(1.5)
            t_kill = time.perf_counter()
            print("  [%.3f] sending SIGTERM" % (t_kill - t0))
            proc.terminate()
            print("  [%.3f] terminate() called" % (time.perf_counter() - t0))

        threading.Thread(target=killer, daemon=True).start()
        rc = proc.wait()
        t1 = time.perf_counter()
        print("  [%.3f] ffplay exited rc=%s" % (t1 - t0, rc))
        if t1 - t0 < 2.0:
            print("  Audio should have cut near 1.5s. Abort mechanism works.")
        else:
            print("  Audio played to end — abort did NOT work.")
    finally:
        os.unlink(wav_path)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'both'
    if mode in ('gap', 'both'):
        probe_gap()
        time.sleep(0.5)
    if mode in ('abort', 'both'):
        probe_abort()
    print("\nDone.")
