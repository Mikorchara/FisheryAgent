"""Independent CLI; shares only the existing approved Session controller."""
import json


def main(argv=None):
    # Startup/import errors happen before the shared controller's JSON boundary.
    # Do not expose missing module names, paths or exception messages.
    try:
        from .session_run_trial_cli import main as session_main
    except Exception as error:
        if isinstance(error,ModuleNotFoundError):code='HYBRID_CLI_DEPENDENCY_MISSING'
        elif isinstance(error,ImportError):code='HYBRID_CLI_IMPORT_FAILED'
        elif isinstance(error,SyntaxError):code='HYBRID_CLI_SOURCE_INVALID'
        else:code='HYBRID_CLI_STARTUP_FAILED'
        print(json.dumps(dict(code=code,stage='startup',automatic_retry=False)),flush=True)
        return 1
    return session_main(argv,hybrid=True)


if __name__ == '__main__':raise SystemExit(main())
