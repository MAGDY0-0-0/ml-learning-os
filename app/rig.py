"""What this machine can do, read cheaply.

Shown on the dashboard because the hardest part of starting is not believing
the setup is real. "RTX 4060 · torch 2.13.0+cu130 · ready" is a different
feeling from a blank page, and it is true rather than encouraging.

Deliberately avoids `import torch`. That import costs seconds and would make
the app depend on the ML stack, which breaks the property that you can run
this thing without installing a gigabyte of packages you will not touch for
weeks. The version comes from installed package metadata and the GPU from
nvidia-smi, both of which are fast and both of which are allowed to fail.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def describe() -> dict[str, str] | None:
    """GPU and torch, or None when there is nothing worth saying."""
    out: dict[str, str] = {}

    try:
        from importlib.metadata import version

        out["torch"] = version("torch")
    except Exception:  # noqa: BLE001 - torch simply may not be installed
        pass

    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            name, driver, mem = (p.strip() for p in r.stdout.strip().splitlines()[0].split(","))
            out["gpu"] = name.replace("NVIDIA GeForce ", "")
            out["driver"] = driver
            out["vram"] = f"{round(int(mem) / 1024)} GB"
    except Exception:  # noqa: BLE001 - no GPU, no driver, no nvidia-smi
        pass

    return out or None
