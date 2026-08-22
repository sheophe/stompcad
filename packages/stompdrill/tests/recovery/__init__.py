"""Independent read-back of what this project's emitters write.

Test support, not shipped: no caller outside a test parses an Excellon file
or a drawing. Each module here reads what our emitters write and nothing
else, and none of them may import ``stompdrill`` -- a recovery that inverts
its emitter's own transform proves the emitter self-consistent and nothing
more. ``test_recovery.py`` holds the gate that enforces it.
"""

from __future__ import annotations

__all__: list[str] = []
