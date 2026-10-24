"""Future integration extension points.

Each adapter defines the interface a later phase implements. In Phase 1 all
adapters are disabled/no-op: no GPU initialization, no model downloads, no
media processing. They exist so the API surface and diagnostics are stable
from day one.
"""
