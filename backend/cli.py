#!/usr/bin/env python3
"""Diagnostic CLI for the same engine used by Millennium; never launches ACCELA GUI."""
import argparse
import json
from pathlib import Path
import time

from components import ROOT
from jobs import ACTIONS, JobManager, TERMINAL


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=sorted(ACTIONS))
    parser.add_argument('--args', default='{}', help='Arguments as JSON')
    options = parser.parse_args()
    path = ROOT/'settings.json'
    manager = JobManager(lambda: json.loads(path.read_text()) if path.exists() else {})
    identity = manager.enqueue(options.action, json.loads(options.args))['job_id']
    previous = None
    try:
        while True:
            snapshot = manager.snapshot()
            job = next(j for j in snapshot['jobs'] if j['id'] == identity)
            if job['message'] != previous:
                print(job['message'], flush=True); previous = job['message']
            if job['prompt']:
                prompt = job['prompt']
                print(json.dumps(prompt, indent=2, ensure_ascii=False))
                answer = input("JSON response (null to cancel):")
                value = json.loads(answer)
                manager.reply(identity, prompt['id'], value, cancel=value is None)
            if job['status'] in TERMINAL:
                if job['status'] != 'done':
                    raise RuntimeError(job['message'])
                print(json.dumps(job['result'], indent=2, ensure_ascii=False))
                break
            time.sleep(.15)
    except KeyboardInterrupt:
        manager.cancel(identity)
        raise SystemExit(130)
    finally:
        manager.close()
        manager.thread.join(3)


if __name__ == '__main__':
    main()
