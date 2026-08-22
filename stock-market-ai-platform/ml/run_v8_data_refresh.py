"""Canonical scheduler entry point for the Stock V8 production data path.

The implementation remains import-compatible with the former V5 scheduler
module while deployments migrate their launch command to this V8 entry point.
"""

if __package__:
    from .run_v5_data_refresh import *  # noqa: F401,F403
    from .run_v5_data_refresh import main
else:
    from run_v5_data_refresh import *  # noqa: F401,F403
    from run_v5_data_refresh import main


if __name__ == "__main__":
    main()
