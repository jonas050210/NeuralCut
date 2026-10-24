"""GPU resource management extension point (Phase 3+).

Detection is best-effort and dependency-free: no NVML/CUDA bindings are
imported at startup. On Windows laptops without an NVIDIA GPU this reports
"no GPU detected" and the app keeps working (CPU-only, models optional).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuralcut.backend.di import Container

import shutil


class GpuManagerAdapter:
    """Best-effort GPU detection, no heavy bindings."""

    def __init__(self, container: "Container") -> None:
        self.container = container

    def status(self) -> dict:
        cuda = shutil.which("nvidia-smi") is not None
        return {
            "gpu_detected": cuda,
            "detail": "nvidia-smi found on PATH" if cuda else "no NVIDIA GPU tooling detected",
            "note": "NeuralCut does not require an NVIDIA GPU",
        }
