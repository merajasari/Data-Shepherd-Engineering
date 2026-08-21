"""Compatibility entry point for the frozen V8 forward paper/holdout runner.

The operational V8 implementation lives in ``ml.v8.holdout_runner``.  Keep this
small module as the stable scheduler/CLI entry point so launchd and manual
commands can invoke ``python -m ml.v8.paper_runner`` without duplicating any
strategy logic or weakening the frozen-spec safety checks.
"""

from ml.v8.holdout_runner import main


if __name__ == "__main__":
    main()
