"""Shared count dispatch and error handling."""

from pathlib import Path

from ._result import CountResult, InvalidEvidence, UnsupportedCount


def run_count(task, path, prompt):
    try:
        if task is None:
            suffix = Path(path).suffix.lower()
            raise UnsupportedCount(f"Counting does not support {suffix or 'this input'}.")
        return task(Path(path), prompt)
    except InvalidEvidence as error:
        return CountResult(status="unsupported", detail=str(error), invalid_evidence=True)
    except UnsupportedCount as error:
        return CountResult(status="unsupported", detail=str(error))
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        return CountResult(status="failed", detail=type(error).__name__)
    except Exception as error:
        if type(error).__module__.startswith(("google.", "httpx", "httpcore")):
            return CountResult(status="failed", detail=type(error).__name__)
        raise
