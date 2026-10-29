"""
Helpers shared by the stages: error and warning reporting, retries, formatting and the final summary.
"""
import asyncio
import time

from core import shared_state
from core.constants import FileStatus, LogColor, Step, MAX_ATTEMPTS, RETRY_DELAYS

class PermanentError(Exception):
    """
    An error that would fail again on every attempt (wrong id, missing file...), so it is not retried.
    """

def report_failure(step: Step, file_name, reason):
    """
    Prints the error right away and stores it for the final summary.
    """
    print(f"{LogColor.LIGHT_RED}[{step.value}] \"{file_name}\": {reason}{LogColor.END}")
    with shared_state.mutex:
        shared_state.errors.append((step, file_name, reason))

def report_warning(step: Step, file_name, reason):
    """
    Prints something to check by hand (the movie still goes on) and stores it for the final summary.
    """
    print(f"{LogColor.YELLOW}[{step.value}] \"{file_name}\": {reason}{LogColor.END}")
    with shared_state.mutex:
        shared_state.warnings.append((step, file_name, reason))

def _handle_failed_attempt(step: Step, file_name, attempt, error, permanent_errors):
    """
    Raises if the error must not be retried. Otherwise returns (seconds to wait, whether the attempt counts).
    """
    if isinstance(error, PermanentError) or isinstance(error, permanent_errors):
        raise error
    # Telegram's FloodWaitError is a limit, not a failure: wait the seconds it asks without counting the attempt
    flood_wait = getattr(error, "seconds", None)
    if flood_wait:
        print(f"{LogColor.YELLOW}[{step.value}] \"{file_name}\": Telegram asks to wait {flood_wait}s (flood limit), waiting...{LogColor.END}")
        return flood_wait, False
    if attempt >= MAX_ATTEMPTS:
        raise RuntimeError(f"{error} (failed after {MAX_ATTEMPTS} attempts)") from error
    delay = RETRY_DELAYS[attempt - 1]
    print(f"{LogColor.YELLOW}[{step.value}] \"{file_name}\": attempt {attempt}/{MAX_ATTEMPTS} failed ({error}), retrying in {delay}s{LogColor.END}")
    return delay, True

def with_retries(step: Step, file_name, operation, permanent_errors=()):
    """
    Runs operation() and retries it if it fails, up to MAX_ATTEMPTS times.
    permanent_errors: extra exception types that are not retried, like PermanentError.
    """
    attempt = 1
    while True:
        try:
            return operation()
        except Exception as e:
            delay, counts = _handle_failed_attempt(step, file_name, attempt, e, permanent_errors)
            time.sleep(delay)
            attempt += counts

async def with_retries_async(step: Step, file_name, operation, permanent_errors=()):
    """
    Same as with_retries, for async operations: awaits operation() and retries it if it fails.
    """
    attempt = 1
    while True:
        try:
            return await operation()
        except Exception as e:
            delay, counts = _handle_failed_attempt(step, file_name, attempt, e, permanent_errors)
            await asyncio.sleep(delay)
            attempt += counts

def format_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024

def format_duration(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"

def _print_table(title, rows, color):
    step_width = max(len("STEP"), *(len(step.value) for step, _, _ in rows))
    file_width = max(len("FILE"), *(len(file_name) for _, file_name, _ in rows))
    print(f"\n{color}{title} ({len(rows)})")
    print(f"  {'STEP':<{step_width}}  {'FILE':<{file_width}}  REASON")
    for step, file_name, reason in rows:
        print(f"  {step.value:<{step_width}}  {file_name:<{file_width}}  {reason}")
    print(LogColor.END, end="")

def print_summary(item_label):
    """
    Prints how many items were uploaded and the tables of errors and warnings. item_label: "movies"...
    """
    with shared_state.mutex:
        errors = list(shared_state.errors)
        warnings = list(shared_state.warnings)
        items = list(shared_state.items)

    # Items that did not finish without a recorded failure (should not happen)
    failed_files = {file_name for _, file_name, _ in errors}
    for item in items:
        if item.status != FileStatus.UPLOADED and item.file_name not in failed_files:
            errors.append((Step.UNKNOWN, item.file_name, f"Stopped with status {item.status.name}"))

    uploaded = sum(1 for item in items if item.status == FileStatus.UPLOADED)
    # Files skipped while reading the folder never became items, but they count in the total
    total = len(items) + sum(1 for step, _, _ in errors if step == Step.READ)

    print("\n================ SUMMARY ================")
    print(f"Uploaded: {uploaded} of {total} {item_label}")
    if not errors and not warnings:
        print(f"{LogColor.LIGHT_GREEN}No errors{LogColor.END}")
        return
    if errors:
        _print_table("ERRORS", errors, LogColor.LIGHT_RED)
    if warnings:
        _print_table("WARNINGS", warnings, LogColor.YELLOW)
