"""Hardware boundary fixture: the parent worker, process lifecycle and API stay real."""

import json
from pathlib import Path
import sys
import time

directory = Path(sys.argv[1])
scenario = sys.argv[2]


def state(status, **extra):
    pending = directory / "state.tmp"
    pending.write_text(json.dumps({"status": status, **extra}))
    pending.replace(directory / "state.json")


state("acquiring", page_count=0)
if scenario == "heartbeat":
    for count in range(100):
        state("page_scanned", page_count=count)
        time.sleep(0.1)
else:
    (directory / "result.pdf").write_bytes(b"%PDF-1.4\nregression\n")
    state("completed", page_count=1)
    time.sleep(0.6)
