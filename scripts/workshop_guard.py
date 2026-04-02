#!/usr/bin/env python3
"""Workshop guard wrapper.

Preferred entrypoint for the 需求研讨流程.
Delegates to scripts/brief_guard.py for backward compatibility.
"""

from brief_guard import main


if __name__ == "__main__":
    raise SystemExit(main())
