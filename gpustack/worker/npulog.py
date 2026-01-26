import logging
import os
import re
from datetime import datetime
from typing import List, Dict, Any, Tuple, Union
from gpustack.schemas.workers import WorkerStatus

logger = logging.getLogger(__name__)

# Log directory path for Ascend GPU logs
_ASCEND_LOG_DIR = "/root/ascend/log/run"


def _extract_timestamp_from_filename(file_name: str) -> int:
    """
    Extract timestamp from log filename.

    Args:
        file_name: Log filename, format like 'device-3719851_20251217170113217.log'

    Returns:
        int: Extracted timestamp from filename, or 0 if parsing fails
    """
    try:
        # Split filename by '_' and get the timestamp part
        # Format: device-<id>_<timestamp>.log
        timestamp_part = file_name.split('_')[1]
        # Remove .log extension
        timestamp_str = timestamp_part.split('.')[0]
        # Convert to integer
        return int(timestamp_str)
    except (IndexError, ValueError):
        # Return 0 if parsing fails
        return 0


def _get_latest_log_files(device_log_dir: str, last_file: str = None) -> List[str]:
    """
    Get log files for a specific device, filtered by timestamp comparison with last_file.

    Args:
        device_log_dir: Full path to the device's log directory
        last_file: Last processed log filename (without directory)

    Returns:
        List of filenames sorted by timestamp (oldest first)
        - If last_file exists: return all files with timestamp >= last_file's timestamp
        - If last_file doesn't exist: return only the newest file
    """
    if not os.path.exists(device_log_dir):
        logger.warning(f"Device log directory not found: {device_log_dir}")
        return []

    try:
        # Get all log files in the directory with their timestamps
        files_with_timestamps = []
        for file_name in os.listdir(device_log_dir):
            file_path = os.path.join(device_log_dir, file_name)
            if os.path.isfile(file_path):
                # Extract timestamp from filename
                timestamp = _extract_timestamp_from_filename(file_name)
                files_with_timestamps.append((file_name, timestamp))

        # Sort all files by timestamp (oldest first)
        files_with_timestamps.sort(key=lambda x: x[1])

        # Extract just the filenames from the sorted list
        sorted_files = [file_name for file_name, _ in files_with_timestamps]

        if not last_file:
            return sorted_files[-5:] if sorted_files else []

        # Extract timestamp from last_file
        last_timestamp = _extract_timestamp_from_filename(last_file)

        # Filter files with timestamp >= last_timestamp
        filtered_files = [
            file_name
            for file_name, timestamp in files_with_timestamps
            if timestamp >= last_timestamp
        ]

        return filtered_files
    except Exception as e:
        logger.error(f"Failed to get log files from {device_log_dir}: {e}")
        return []


# Regex pattern to parse log timestamps from Ascend GPU logs
# Actual log line format: [INFO] CCECPU(11837,aicpu_scheduler):2025-11-06-19:28:23.094.520 [main.cpp:283][main][tid:11837] Message
# All content after timestamp is captured as a single message group
_LOG_TIMESTAMP_PATTERN = re.compile(
    r'^\[(\w+)\].*?:(\d{4}-\d{2}-\d{2}-\d{2}:\d{2}:\d{2}\.\d{3}\.\d{3})\s*(.*)$'
)


def _parse_log_timestamp(log_line: str) -> Union[Tuple[int, str, str], None]:
    """
    Parse timestamp, loglevel, and message from a log line.

    Args:
        log_line: A single line from the log file

    Returns:
        Tuple[int, str, str] if parsing succeeds, None otherwise
        int: Unix timestamp in microseconds since 1970
        str: Original loglevel from log line
        str: Message content
    """
    match = _LOG_TIMESTAMP_PATTERN.match(log_line)
    if not match:
        logger.warning(f"Unexpected log line format: {log_line}")
        return None

    loglevel, timestamp_str, message = match.groups()

    # Convert timestamp string from format "YYYY-MM-DD-HH:MM:SS.mmm.mmm" to datetime
    # First part: YYYY-MM-DD-HH:MM:SS
    # Second part: .mmm.mmm (milliseconds.microseconds)
    # Combine to YYYY-MM-DD-HH:MM:SS.mmmmmm for strptime
    timestamp_parts = timestamp_str.split('.')
    if len(timestamp_parts) != 3:
        logger.warning(
            f"Unexpected timestamp format, parts count: {len(timestamp_parts)}, expected 3: {timestamp_str}"
        )
        return None

    # Format: YYYY-MM-DD-HH:MM:SS.mmm.mmm
    base_time = timestamp_parts[0]
    ms = timestamp_parts[1].zfill(3)
    us = timestamp_parts[2].zfill(3)
    # Combine to YYYY-MM-DD-HH:MM:SS.mmmmmm
    formatted_time = f"{base_time}.{ms}{us}"

    # Only wrap the datetime parsing line in try-except
    try:
        dt = datetime.strptime(formatted_time, "%Y-%m-%d-%H:%M:%S.%f")
    except ValueError as e:
        logger.error(f"Failed to parse timestamp {timestamp_str}: {e}")
        return None

    # Convert to Unix timestamp in microseconds since 1970
    timestamp = int(dt.timestamp() * 1_000_000)
    return timestamp, loglevel, message


def _process_log_file(
    file_path: str, device_logs: List[Dict[str, Any]], last_timestamp: int = 0
) -> int:
    """
    Process a single log file, adding ERROR and WARNING entries to device_logs.

    Args:
        file_path: Path to the log file
        device_logs: List to append log entries to
        last_timestamp: Only process entries after this timestamp (in microseconds)

    Returns:
        int The maximum timestamp found in this file (in microseconds)
    """
    try:
        with open(file_path, 'r') as f:
            # Process lines one by one for better memory efficiency
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parsed = _parse_log_timestamp(line)
                if not parsed:
                    continue

                timestamp, loglevel, message = parsed

                # Skip entries older than last_timestamp
                if timestamp <= last_timestamp:
                    continue
                last_timestamp = timestamp

                # Only keep ERROR and WARNING entries
                if loglevel not in ["ERROR", "WARNING", "WARN", "Err", "Error"]:
                    continue

                # Normalize loglevel for consistency
                if loglevel in ["ERROR", "Err", "Error"]:
                    normalized_loglevel = "ERROR"
                else:
                    normalized_loglevel = "WARNING"

                # Add log entry
                # Convert microseconds to datetime for display
                dt = datetime.fromtimestamp(timestamp / 1_000_000)
                device_logs.append(
                    {
                        "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S.%f"),
                        "loglevel": normalized_loglevel,
                        "message": message,
                    }
                )
    except Exception as e:
        logger.error(f"Failed to process log file {file_path}: {e}")

    return last_timestamp


def inject_npu_logdir(
    device_logs: List[Dict[str, Any]], last_info: Dict[str, Any], device_log_dir: str
) -> Dict[str, Any]:
    """
    Process logs for a single device from a specific log directory.

    Args:
        device_logs: List to append log entries to
        last_info: Previous device info with 'file_path' and 'timestamp'
        device_log_dir: Full path to the device's log directory

    Returns:
        Updated device info with 'file_path' and 'timestamp'
    """
    # Extract last_file and last_ts from last_info
    if last_info.get("file_path") is None:
        last_info["file_path"] = None
    if last_info.get("timestamp") is None:
        last_info["timestamp"] = 0

    # Get latest log files for this device
    log_files = _get_latest_log_files(device_log_dir, last_info["file_path"])

    for file_name in log_files:
        full_path = os.path.join(device_log_dir, file_name)

        if file_name == last_info["file_path"]:
            last_info["timestamp"] = _process_log_file(
                full_path, device_logs, last_info["timestamp"]
            )
        else:
            last_info["timestamp"] = _process_log_file(full_path, device_logs, 0)
            last_info["file_path"] = file_name

    return last_info


def inject_npu_devicelogs(
    gpu_devices: List[Any],
    npu_log_timestamp: Dict[int, Dict[str, Any]],
    log_dir: str = _ASCEND_LOG_DIR,
) -> Dict[int, Dict[str, Any]]:
    """
    Collect GPU logs for all devices and inject them into the gpu_devices list.

    Args:
        gpu_devices: List of GPU device information objects
        npu_log_timestamp: Global timestamp tracking structure
        log_dir: Base log directory (for testing purposes)

    Returns:
        Updated npu_log_timestamp structure
    """
    updated_timestamp = npu_log_timestamp.copy()

    for device in gpu_devices:
        if device.vendor != "ascend":
            continue

        # Use attribute assignment for Pydantic model
        device.log = []
        device_id = device.index

        # Process logs for this device
        if not updated_timestamp.get(device_id):
            updated_timestamp[device_id] = {}

        inject_npu_logdir(
            device.log,
            updated_timestamp[device_id],
            os.path.join(log_dir, f"device-{device_id}"),
        )

    return updated_timestamp


def inject_npu_globallog(
    status: WorkerStatus,
    npu_globallog_timestamp: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Collect global NPU logs from the plog directory and inject them into the provided log list.

    Args:
        status: WorkerStatus object to append global log entries to
        npu_globallog_timestamp: Timestamp tracking structure for global logs

    Returns:
        Updated timestamp tracking structure for global logs
    """

    for device in status.gpu_devices:
        if device.vendor == "ascend":
            break
    else:
        return npu_globallog_timestamp

    # Initialize timestamp structure if not provided
    updated_timestamp = npu_globallog_timestamp.copy()

    status.aicard_log = []

    # Use inject_npu_logdir to process the global log directory
    updated_timestamp = inject_npu_logdir(
        status.aicard_log, updated_timestamp, os.path.join(_ASCEND_LOG_DIR, "plog")
    )

    return updated_timestamp


if __name__ == "__main__":
    """
    Test the inject_npu_logs function with real data from /root/ascend/log/run.
    """
    import time

    def run_log_collection_test(gpu_devices, npu_log_timestamp):
        """
        Run log collection test and print results.
        This function contains merged functionality of print_device_results and print_timestamp_structure.
        """
        result_timestamp = inject_npu_devicelogs(gpu_devices, npu_log_timestamp)

        # Print results for all devices (merged from print_device_results)
        for i, device in enumerate(gpu_devices):
            logs = device.get('log', [])
            print(f"Device {i} logs collected: {len(logs)}")
            # Print first 3 logs if any
            for log in logs:
                print(
                    f"  - {log['timestamp']} {log['loglevel']}: {log['message'][:120]}..."
                )

        # Print timestamp structure (merged from print_timestamp_structure)
        print("\nReturned timestamp structure:")
        for device_id, info in result_timestamp.items():
            print(f"{device_id}: {info['file_path']}  {int(info['timestamp'])}")

        return result_timestamp

    # Initialize gpu_devices only once
    gpu_devices = [{"index": i} for i in range(8)]
    npu_log_timestamp = {}

    # Test Case 1: Initial call with empty timestamp
    print("=== Test Case 1: Initial call with empty timestamp ===")
    npu_log_timestamp = run_log_collection_test(gpu_devices, npu_log_timestamp)

    # Test Case 2: Second call with existing timestamp
    print("\n=== Test Case 2: Second call ===")
    npu_log_timestamp = run_log_collection_test(gpu_devices, npu_log_timestamp)

    # Test Case 3: Add new logs and new file
    print("\n=== Test Case 3: Add new logs ===")
    device_0_dir = os.path.join(_ASCEND_LOG_DIR, "device-0")

    if npu_log_timestamp and 0 in npu_log_timestamp:
        # Get device 0 file
        latest_file = os.path.join(device_0_dir, npu_log_timestamp[0]['file_path'])

        # Append new error log
        print(f"\nAdding new error log to: {latest_file}")
        with open(latest_file, 'a') as f:
            time.sleep(0.1)
            t = datetime.now()
            log_time = t.strftime("%Y-%m-%d-%H:%M:%S.%f")[:-3]
            f.write(
                f"[ERROR] CCECPU(12345,aicpu_scheduler):{log_time}.000 [test.cpp:123][test_func][tid:12345] Test new error\n"
            )

        # Create new log file
        time.sleep(0.1)
        t = datetime.now()
        ts_str = t.strftime("%Y%m%d%H%M%S%f")[:-3]
        new_file = os.path.join(device_0_dir, f"device-test_{ts_str}.log")
        # Prepare log content
        log_time = t.strftime("%Y-%m-%d-%H:%M:%S.%f")[:-3]
        log_content = f"[WARNING] CCECPU(12345,aicpu_scheduler):{log_time}.000 [test.cpp:123][test_func][tid:12345] Test new file warning\n"
        # Write to file
        with open(new_file, 'w') as f:
            f.write(log_content)
        # Only remove the specific content output line, keep the rest
        print(f"Created new log file: {new_file}")

        # Call again with all devices and check results
        npu_log_timestamp = run_log_collection_test(gpu_devices, npu_log_timestamp)

        # Clean up
        print(f"\nCleaning up - removing: {new_file}")
        os.remove(new_file)
    else:
        print(f"No log files found in {device_0_dir}")
