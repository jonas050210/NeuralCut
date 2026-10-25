"""Optional QLoRA training package (home-PC use only).

This package is *not* part of the NeuralCut runtime: it imports no heavy
dependencies at package import time, is excluded from the packaged
backend's requirements, and must be installed into a separate
environment (see requirements-training.txt / scripts/setup_training.*).

Training never runs automatically, never touches held-out data, and its
output is only ever an adapter directory that becomes a *candidate* for
the existing human-gated promotion flow (backend/improvement).
"""
