import logging
import time
import subprocess
from datetime import datetime
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Track the last timestamp in microseconds since boot
_last_timestamp = 0

# Cache system boot time (Unix timestamp in seconds)
_boot_time = 0


def parse_line(line: str) -> tuple[int, str, str] | None:
    """
    Parse a single line from dmesg -x output.

    Args:
        line: A line from dmesg -x output

    Returns:
        tuple: (boot_time_us, level, message) if parsing succeeds, None otherwise
        boot_time_us: Time in microseconds since boot
        level: Log level (emerg, alert, crit, err, warn, notice, info, debug)
        message: Log message content
    """
    # dmesg -x output format: facility  :level  : [ 1933189.245229] message
    if ": [" not in line or "] " not in line:
        return None

    # Split the line into header (facility:level) and rest (timestamp + message)
    header_part, timestamp_message = line.split(": [", 1)
    # Split rest into timestamp and message
    timestamp_str, message = timestamp_message.split("] ", 1)

    # Parse facility and level from header_part
    # Format: "facility  :level"
    if ":" not in header_part:
        return None

    facility, level = header_part.split(":", 1)
    facility = facility.strip()
    level = level.strip().lower()

    # Process timestamp string into microseconds
    # Format: " 1933189.245229" -> 1933189245229 microseconds
    time_str = timestamp_str.strip()

    # Split into seconds and microseconds parts
    if "." in time_str:
        seconds_part, micros_part = time_str.split(".", 1)
        # Ensure micros_part has exactly 6 digits (pad with zeros or truncate)
        micros_part = (micros_part + "000000")[:6]
    else:
        seconds_part = time_str
        micros_part = "000000"

    # Combine into microseconds integer
    try:
        boot_time_us = int(seconds_part) * 1000000 + int(micros_part)
    except ValueError:
        return None

    return boot_time_us, level, message


def add_to_log(
    logs: List[Dict[str, Any]], message: str, boot_time_us: int, severity: str
) -> None:
    """
    Add a log entry to the logs list with proper formatting.

    Args:
        logs: List to append log entries to
        message: The log message (pure ASCII)
        boot_time_us: The time in microseconds since boot as integer
        severity: The severity (ERROR or WARNING)
    """
    global _boot_time
    # Lazy initialization for boot time (set when first used)
    if _boot_time == 0:
        try:
            with open("/proc/stat") as f:
                for line in f:
                    if line.startswith("btime "):
                        _boot_time = int(line.split()[1])
                        break
        except Exception as e:
            logger.error(f"Failed to get system boot time: {e}")
            _boot_time = int(time.time())
    # Calculate total microseconds since epoch using integer arithmetic (avoid floating point)
    total_micros = (_boot_time * 1000000) + boot_time_us
    seconds = total_micros // 1000000
    micros = total_micros % 1000000
    # Construct datetime object from integer seconds and microseconds
    dt = datetime.fromtimestamp(seconds).replace(microsecond=micros)
    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    logs.append({"timestamp": formatted_time, "severity": severity, "message": message})


def is_new_log(timestamp: int) -> bool:
    """
    Check if the log with the given timestamp is new.
    If it's new, update the last timestamp position.

    Args:
        timestamp: The timestamp in microseconds since boot

    Returns:
        bool: True if the log is new, False otherwise
    """
    global _last_timestamp
    is_new = False

    if timestamp > _last_timestamp:
        is_new = True
        _last_timestamp = timestamp

    return is_new


def _inject_system_logs(logs: List[Dict[str, Any]]) -> bool:
    """
    Collect system logs from /dev/kmsg using dmesg command.
    This function reads new logs since the last call and appends them to the provided logs list.
    Only logs with severity ERROR or WARNING are included.

    Args:
        logs: List to append log entries to.

    Returns:
        bool: True if the operation succeeded, False otherwise.
    """
    if logs is None:
        return False

    try:
        # Use dmesg with -x to get facility, level, and timestamp information in one call
        result = subprocess.run(
            ["dmesg", "-x"], capture_output=True, text=True, check=True
        )
        dmesg_output = result.stdout

        # Process each line from dmesg -x output
        for line in dmesg_output.splitlines():
            line = line.strip()
            if not line:
                continue

            # Parse the line using our new parse_line function
            parsed = parse_line(line)
            if parsed is None:
                continue

            boot_time_us, level, message = parsed

            # Check if it's a warning or error (case insensitive)
            severity = ""
            if level in ["emerg", "alert", "crit", "err"]:
                severity = "ERROR"
            elif level in ["warn"]:
                severity = "WARNING"
            else:
                # Skip info and debug messages
                continue

            # Check if this is a new log
            if is_new_log(boot_time_us):
                # Add the log entry (using ASCII only)
                add_to_log(
                    logs,
                    message.encode('ascii', 'ignore').decode('ascii'),
                    boot_time_us,
                    severity,
                )

        return True
    except Exception as e:
        logger.error(f"Failed to collect system logs: {e}")
        return False


if __name__ == "__main__":
    """
    Test the _inject_system_logs function.
    """
    print("Testing _inject_system_logs function...")

    # First call - should get all existing warnings/errors
    print("\n1. First call:")
    logs = []
    success = _inject_system_logs(logs)
    print(f"   Operation {'succeeded' if success else 'failed'}")
    print(f"   Found {len(logs)} entries")
    for entry in logs:
        print(f"   {entry['timestamp']} {entry['severity']}: {entry['message']}")

    # Second call - should get nothing new
    print("\n2. Second call (should be empty):")
    logs2 = []
    success = _inject_system_logs(logs2)
    print(f"   Operation {'succeeded' if success else 'failed'}")
    print(f"   Found {len(logs2)} entries")
    for entry in logs2:
        print(f"   {entry['timestamp']} {entry['severity']}: {entry['message']}")

    # Write a test warning
    print("\n3. Writing test warning...")
    import os

    os.system("echo '<4>test: this is a test warning' > /dev/kmsg")
    time.sleep(0.5)  # Give some time for the message to be processed

    # Third call - should get the new warning
    print("\n4. Third call (should find the warning):")
    logs3 = []
    success = _inject_system_logs(logs3)
    print(f"   Operation {'succeeded' if success else 'failed'}")
    print(f"   Found {len(logs3)} entries")
    for entry in logs3:
        print(f"   {entry['timestamp']} {entry['severity']}: {entry['message']}")

    print("\nTest completed.")
