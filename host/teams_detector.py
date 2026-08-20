r"""
host/teams_detector.py - Local Microsoft Teams status & activity detector for Windows.

Architecture Overview:
  This module implements a zero-network, zero-Graph-API presence detection engine.
  Traditional enterprise presence integrations require tenant-level Azure AD / Entra ID
  admin consent and cloud API tokens. This module avoids all cloud authentication by
  monitoring local OS and application indicators on Windows:

  1. Process Monitoring (WindowsProcessTracker):
     - Uses Win32 Toolhelp32 snapshots (`CreateToolhelp32Snapshot`) to verify if
       Teams executable processes (`ms-teams.exe`, `msteams.exe`, `teams.exe`) are running.

  2. Workstation State (WindowsSessionTracker):
     - Uses `OpenInputDesktop` from user32.dll to determine if the workstation
       is locked (Win+L) or on a secure desktop / switch screen.

  3. Hardware Capability Access (WindowsHardwareTracker):
     - Queries Windows Capability Access Manager (CAM) in the Registry:
       `HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore`
       to inspect `LastUsedTimeStart` vs `LastUsedTimeStop` timestamps for microphone
       and webcam sensors, detecting active voice/video calls in real-time.

  4. Local Log Tailing (TeamsLogTailer):
     - Incrementally reads the latest `MSTeams_*.log` file from the local AppData package.
     - Parses presence update events (`UserPresenceAction`), broadcast states (`UserDataGlobalState`),
       and active meeting counts (`meetingstore...meetings size`).
     - Supports real-time log rotation across application restarts.

  5. State Synthesis (TeamsDetector):
     - Aggregates all sensor inputs into a single canonical `TeamsStatusEvent`.
     - Applies priority rules: NotRunning > Workstation Locked > In A Call / Meeting > Explicit Presence.
     - Provides delta change detection via `poll_for_change()`.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import glob
import json
import os
import re
from typing import List, Optional, Tuple
import winreg


class TeamsAvailability(str, Enum):
    """
    Standard enumeration of possible Microsoft Teams user availability states.
    Inherits from str so instances serialize naturally to strings.
    """
    AVAILABLE = "Available"
    BUSY = "Busy"
    DO_NOT_DISTURB = "DoNotDisturb"
    BE_RIGHT_BACK = "BeRightBack"
    AWAY = "Away"
    OFFLINE = "Offline"
    UNKNOWN = "Unknown"


# Canonical status normalization mapping:
# Maps various casing variants, abbreviations, and internal Teams statuses to standard enum members.
STATUS_MAP = {
    "available": TeamsAvailability.AVAILABLE,
    "busy": TeamsAvailability.BUSY,
    "donotdisturb": TeamsAvailability.DO_NOT_DISTURB,
    "dnd": TeamsAvailability.DO_NOT_DISTURB,
    "focusing": TeamsAvailability.DO_NOT_DISTURB,
    "presenting": TeamsAvailability.DO_NOT_DISTURB,
    "berightback": TeamsAvailability.BE_RIGHT_BACK,
    "brb": TeamsAvailability.BE_RIGHT_BACK,
    "away": TeamsAvailability.AWAY,
    "inactive": TeamsAvailability.AWAY,
    "idle": TeamsAvailability.AWAY,
    "offline": TeamsAvailability.OFFLINE,
    "notrunning": TeamsAvailability.OFFLINE,
    "unknown": TeamsAvailability.UNKNOWN,
    "presenceunknown": TeamsAvailability.UNKNOWN,
}


def normalize_status(raw: str) -> TeamsAvailability:
    """
    Normalizes a raw presence string from logs or external inputs into a canonical TeamsAvailability enum.

    Args:
        raw (str): Raw string such as 'Busy', 'dnd', 'Focusing', 'Away'.

    Returns:
        TeamsAvailability: The matching canonical enum value (or TeamsAvailability.UNKNOWN if unrecognized).
    """
    cleaned = raw.strip().lower()
    return STATUS_MAP.get(cleaned, TeamsAvailability.UNKNOWN)


@dataclass
class TeamsStatusEvent:
    """
    Immutable data snapshot representing the aggregated status of Microsoft Teams at a given moment.

    Attributes:
        status (str): Effective synthesized high-level status (e.g., 'Available', 'InACall', 'Away', 'NotRunning').
        availability (str): Underlying raw Teams presence availability (e.g., 'Busy', 'Available').
        in_call (bool): True if user is in an active voice/video call or meeting.
        in_meeting (bool): True if meeting store reports 1 or more active meetings.
        mic_active (bool): True if Windows CAM registry indicates active microphone usage by Teams.
        camera_active (bool): True if Windows CAM registry indicates active webcam usage by Teams.
        is_running (bool): True if a Microsoft Teams process is detected in the process table.
        is_locked (bool): True if the Windows workstation is currently locked.
        timestamp (str): ISO-8601 formatted timestamp string with timezone.
    """
    status: str
    availability: str
    in_call: bool
    in_meeting: bool
    mic_active: bool
    camera_active: bool
    is_running: bool
    is_locked: bool
    timestamp: str

    def to_dict(self) -> dict:
        """
        Converts the status event into a dictionary suitable for JSON serialization and transmission.
        """
        return {
            "type": "teams_status",
            "status": self.status,
            "availability": self.availability,
            "in_call": self.in_call,
            "in_meeting": self.in_meeting,
            "mic_active": self.mic_active,
            "camera_active": self.camera_active,
            "is_running": self.is_running,
            "is_locked": self.is_locked,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        """
        Serializes the event directly to a single-line JSON string.
        """
        return json.dumps(self.to_dict())


class WindowsProcessTracker:
    """
    Detects whether Microsoft Teams desktop processes are running using native Windows Toolhelp32 API.
    
    Why native Win32 API?
    - Spawning `tasklist.exe` or `Get-Process` in PowerShell incurs high CPU and process creation overhead.
    - Toolhelp32 snapshot via ctypes is virtually instantaneous (< 1ms) and requires no external packages.
    """

    # Known executable names across modern "New Teams" (MSIX) and classic Teams
    TEAMS_EXECUTABLES = {"ms-teams.exe", "msteams.exe", "teams.exe"}

    @staticmethod
    def is_running() -> bool:
        """
        Scans active Windows processes to check if any known Microsoft Teams executable is running.

        Returns:
            bool: True if at least one Teams process is currently active, False otherwise.
        """
        # Flag 0x00000002 indicates taking a snapshot of all processes in the system
        TH32CS_SNAPPROCESS = 0x00000002

        # C-compatible struct definition matching Windows Win32 PROCESSENTRY32
        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),  # MAX_PATH = 260
            ]

        # Request system process snapshot from kernel32
        h_snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        # Invalid handle check (-1 or 64-bit unsigned equivalent)
        if h_snap == -1 or h_snap == 0xFFFFFFFFFFFFFFFF:
            return False

        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

        found = False
        try:
            # Walk the process list starting from the first entry
            if ctypes.windll.kernel32.Process32First(h_snap, ctypes.byref(pe)):
                while True:
                    # Decode the null-terminated executable name string
                    exe = pe.szExeFile.decode("utf-8", errors="ignore").strip().lower()
                    if exe in WindowsProcessTracker.TEAMS_EXECUTABLES:
                        found = True
                        break
                    # Advance to the next process entry in the snapshot
                    if not ctypes.windll.kernel32.Process32Next(h_snap, ctypes.byref(pe)):
                        break
        finally:
            # Always close the snapshot handle to avoid OS resource leaks
            ctypes.windll.kernel32.CloseHandle(h_snap)

        return found


class WindowsSessionTracker:
    """
    Checks whether the Windows workstation is currently locked or displaying a secure desktop.
    """

    @staticmethod
    def is_locked() -> bool:
        """
        Determines workstation lock state using user32.dll OpenInputDesktop.

        Mechanism:
          When a Windows workstation is locked (or switching users / displaying UAC),
          the interactive input desktop is switched away from the default desktop to
          the Winlogon secure desktop. Calling `OpenInputDesktop` with desktop access
          rights fails with NULL / Access Denied when the workstation is locked.

        Returns:
            bool: True if the workstation is locked, False if unlocked and active.
        """
        DESKTOP_SWITCHDESKTOP = 0x0100
        # Attempt to open the desktop currently receiving user input
        h_desktop = ctypes.windll.user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if h_desktop:
            # If successful, close the opened desktop handle and report unlocked
            ctypes.windll.user32.CloseDesktop(h_desktop)
            return False
        # Failed to open input desktop -> session is locked or on a secure desktop
        return True


class WindowsHardwareTracker:
    """
    Checks Windows Capability Access Manager (CAM) in the Registry for active microphone & webcam use.

    Mechanism:
      Windows 10/11 tracks hardware access in the Registry under:
      `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\{capability}`
      Each registered application maintains `LastUsedTimeStart` and `LastUsedTimeStop` 64-bit FILETIME values.
      If `LastUsedTimeStart > 0` and `(LastUsedTimeStop == 0 or LastUsedTimeStart > LastUsedTimeStop)`,
      the capability (microphone or camera) is currently active and capturing live audio/video.
    """

    REG_BASE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
    # Package family names for modern Microsoft Teams (MSIX store app & enterprise work/school app)
    TEAMS_PACKAGES = ["MSTeams_8wekyb3d8bbwe", "Microsoft.Teams_8wekyb3d8bbwe"]

    @classmethod
    def _is_capability_in_use(cls, capability: str) -> bool:
        """
        Queries the registry consent store for active sensor usage by Teams.

        Args:
            capability (str): Sensor capability name ('microphone' or 'webcam').

        Returns:
            bool: True if the sensor is currently in active use by Teams, False otherwise.
        """
        # 1. Check packaged (UWP / MSIX) Teams installations
        for pkg in cls.TEAMS_PACKAGES:
            key_path = f"{cls.REG_BASE}\\{capability}\\{pkg}"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    try:
                        stop_time = winreg.QueryValueEx(key, "LastUsedTimeStop")[0]
                    except (FileNotFoundError, OSError):
                        stop_time = 0

                    try:
                        start_time = winreg.QueryValueEx(key, "LastUsedTimeStart")[0]
                    except (FileNotFoundError, OSError):
                        start_time = 0

                    # Active if start timestamp is newer than stop timestamp (or stop has never been recorded)
                    if start_time > 0 and (stop_time == 0 or start_time > stop_time):
                        return True
            except (FileNotFoundError, OSError):
                continue

        # 2. Check NonPackaged entries for classic desktop (Win32) Teams installations
        non_packaged_path = f"{cls.REG_BASE}\\{capability}\\NonPackaged"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, non_packaged_path) as root_key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(root_key, index)
                        index += 1
                        # Inspect subkeys associated with Teams executables
                        if "teams" in subkey_name.lower():
                            with winreg.OpenKey(root_key, subkey_name) as subkey:
                                try:
                                    stop_t = winreg.QueryValueEx(subkey, "LastUsedTimeStop")[0]
                                except (FileNotFoundError, OSError):
                                    stop_t = 0
                                try:
                                    start_t = winreg.QueryValueEx(subkey, "LastUsedTimeStart")[0]
                                except (FileNotFoundError, OSError):
                                    start_t = 0
                                if start_t > 0 and (stop_t == 0 or start_t > stop_t):
                                    return True
                    except OSError:
                        # End of subkey enumeration
                        break
        except (FileNotFoundError, OSError):
            pass

        return False

    @classmethod
    def is_mic_active(cls) -> bool:
        """
        Checks if the microphone is currently active and streaming audio in Teams.
        """
        return cls._is_capability_in_use("microphone")

    @classmethod
    def is_camera_active(cls) -> bool:
        """
        Checks if the webcam is currently active and streaming video in Teams.
        """
        return cls._is_capability_in_use("webcam")


class TeamsLogTailer:
    """
    Tails local Microsoft Teams log files incrementally with log rotation support.

    Teams writes diagnostic logs to `%LOCALAPPDATA%\\Packages\\MSTeams_8wekyb3d8bbwe\\LocalCache\\Microsoft\\MSTeams\\Logs`.
    This tailer tracks the current active log file by byte offset (`file_pos`) to avoid re-reading
    already-processed entries, and seamlessly transitions to newer log files upon log rotation.
    """

    # Regular expression for explicit user presence updates in New Teams
    ACTION_AVAILABILITY_PATTERN = re.compile(
        r"UserPresenceAction:\s*\{[^}]*availability:\s*([A-Za-z]+)",
        re.IGNORECASE,
    )

    # Regular expression for broadcasted global user presence arrays
    GLOBAL_STATE_PATTERN = re.compile(
        r"UserDataGlobalState total number of users:\s*\d+((?:\s*\{[^}]+\})+)",
        re.IGNORECASE,
    )

    # Sub-expression to extract individual availability entries from global state blocks
    ITEM_AVAILABILITY_PATTERN = re.compile(
        r"availability:\s*([A-Za-z]+)",
        re.IGNORECASE,
    )

    # Fallback patterns for legacy / classic Teams log formats
    FALLBACK_PATTERNS = [
        re.compile(r"Setting (?:the )?user status to ([A-Za-z]+)", re.IGNORECASE),
        re.compile(r"Status is ([A-Za-z]+)", re.IGNORECASE),
    ]

    # Pattern to extract active meeting count from meeting store events
    MEETING_SIZE_PATTERN = re.compile(
        r"cross_cloud::meetingstore:\s*(?:global\s+state\s+)?meetings\s+size:\s*(\d+)",
        re.IGNORECASE,
    )

    def __init__(self, log_dir: Optional[str] = None):
        """
        Initializes the log tailer and performs an initial scan to seed availability.

        Args:
            log_dir (str, optional): Custom path to Teams log directory. Defaults to standard New Teams path.
        """
        if log_dir is None:
            self.log_dir = os.path.expandvars(
                r"%LOCALAPPDATA%\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\Logs"
            )
        else:
            self.log_dir = log_dir

        self.current_file: Optional[str] = None
        self.file_pos: int = 0
        self.last_availability: TeamsAvailability = TeamsAvailability.UNKNOWN
        self.meeting_count: int = 0

        # Perform initial scan across existing log entries to establish baseline state
        self._initialize_tailer()

    def _get_latest_log_file(self) -> Optional[str]:
        """
        Finds the most recently modified Teams log file in the log directory.

        Returns:
            str or None: Full path to the newest log file, or None if no logs exist.
        """
        if not os.path.isdir(self.log_dir):
            return None

        # Look for New Teams format MSTeams_*.log first, fallback to *.log
        candidates = glob.glob(os.path.join(self.log_dir, "MSTeams_*.log"))
        if not candidates:
            candidates = glob.glob(os.path.join(self.log_dir, "*.log"))

        if not candidates:
            return None

        # Sort by modification time descending to select newest
        candidates.sort(key=os.path.getmtime, reverse=True)
        return candidates[0]

    def _initialize_tailer(self):
        """
        Reads existing contents of the latest log file on startup to seed state,
        then bookmarks the file position to the end of the file.
        """
        latest = self._get_latest_log_file()
        if not latest:
            return

        self.current_file = latest
        try:
            with open(latest, "r", encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    self._parse_line(line)
                self.file_pos = fp.tell()
        except Exception:
            self.file_pos = 0

    def _parse_line(self, line: str):
        """
        Scans a single log line against regex patterns to extract presence and meeting status.

        Args:
            line (str): Raw line from the Teams log file.
        """
        # 1. Check for specific Action: UserPresenceAction (high confidence)
        action_match = self.ACTION_AVAILABILITY_PATTERN.search(line)
        if action_match:
            status = normalize_status(action_match.group(1))
            if status != TeamsAvailability.UNKNOWN:
                self.last_availability = status
                return

        # 2. Check for UserDataGlobalState multi-user block
        global_match = self.GLOBAL_STATE_PATTERN.search(line)
        if global_match:
            block = global_match.group(1)
            found_availabilities: List[TeamsAvailability] = []
            for item in self.ITEM_AVAILABILITY_PATTERN.finditer(block):
                st = normalize_status(item.group(1))
                if st != TeamsAvailability.UNKNOWN:
                    found_availabilities.append(st)

            # Prioritize active presence over Unknown placeholder
            if found_availabilities:
                self.last_availability = found_availabilities[-1]
                return

        # 3. Check fallback patterns (e.g. classic Teams logs)
        for pat in self.FALLBACK_PATTERNS:
            match = pat.search(line)
            if match:
                st = normalize_status(match.group(1))
                if st != TeamsAvailability.UNKNOWN:
                    self.last_availability = st
                    return

        # 4. Check for meeting size
        m_match = self.MEETING_SIZE_PATTERN.search(line)
        if m_match:
            try:
                self.meeting_count = int(m_match.group(1))
            except ValueError:
                pass

    def poll(self) -> Tuple[TeamsAvailability, int]:
        """
        Polls for new log lines appended since the last poll.
        Handles file rotation if Teams has started writing to a new log file.

        Returns:
            Tuple[TeamsAvailability, int]: Current (availability, active_meeting_count).
        """
        latest = self._get_latest_log_file()

        # Handle log file rotation (Teams launched new session / rotated log file)
        if latest and latest != self.current_file:
            # Finish reading any remaining bytes from the previous file
            if self.current_file and os.path.isfile(self.current_file):
                self._read_incremental(self.current_file)
            # Switch to the new file and reset offset
            self.current_file = latest
            self.file_pos = 0

        # Read any newly appended lines from current file
        if self.current_file and os.path.isfile(self.current_file):
            self._read_incremental(self.current_file)

        return self.last_availability, self.meeting_count

    def _read_incremental(self, file_path: str):
        """
        Seeks to the saved file position, processes newly appended lines, and updates the position.

        Args:
            file_path (str): Path to the log file to read.
        """
        try:
            file_size = os.path.getsize(file_path)
            # If the file shrank (truncated), reset pointer to 0
            if file_size < self.file_pos:
                self.file_pos = 0

            with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                fp.seek(self.file_pos)
                for line in fp:
                    self._parse_line(line)
                self.file_pos = fp.tell()
        except Exception:
            pass


class TeamsDetector:
    """
    Aggregates log tailing, hardware states, process status, and workstation state into unified events.
    
    Synthesizes discrete OS and application signals into a coherent status and supports change polling.
    """

    def __init__(self, log_dir: Optional[str] = None):
        """
        Initializes the TeamsDetector with a configured log tailer.

        Args:
            log_dir (str, optional): Custom path to Teams log directory.
        """
        self.log_tailer = TeamsLogTailer(log_dir)
        self.last_event: Optional[TeamsStatusEvent] = None

    def get_status(self) -> TeamsStatusEvent:
        """
        Queries all trackers, combines their states according to precedence rules,
        and constructs a snapshot `TeamsStatusEvent`.

        Status Precedence Rules:
          1. Process not running  -> 'NotRunning'
          2. Workstation locked   -> 'Away'
          3. In a call / meeting  -> 'InACall' (or preserves DND if user manually set DND)
          4. Known Availability   -> Underlying availability (e.g. 'Busy', 'DoNotDisturb', 'Available')
          5. Default fallback     -> 'Available'

        Returns:
            TeamsStatusEvent: Complete snapshot of current status.
        """
        # Query individual sensor trackers
        is_running = WindowsProcessTracker.is_running()
        is_locked = WindowsSessionTracker.is_locked()
        mic_active = WindowsHardwareTracker.is_mic_active()
        camera_active = WindowsHardwareTracker.is_camera_active()

        # Tail latest log updates
        availability, meeting_count = self.log_tailer.poll()
        in_meeting = meeting_count > 0
        in_call = in_meeting or mic_active

        # Synthesize effective status according to priority rules
        if not is_running:
            effective = "NotRunning"
        elif is_locked:
            effective = "Away"
        elif in_call:
            effective = "InACall" if availability in (TeamsAvailability.BUSY, TeamsAvailability.AVAILABLE) else availability.value
        elif availability != TeamsAvailability.UNKNOWN:
            effective = availability.value
        else:
            effective = "Available"

        # Generate ISO timestamp with local timezone offset
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()

        event = TeamsStatusEvent(
            status=effective,
            availability=availability.value,
            in_call=in_call,
            in_meeting=in_meeting,
            mic_active=mic_active,
            camera_active=camera_active,
            is_running=is_running,
            is_locked=is_locked,
            timestamp=now_iso,
        )
        return event

    def poll_for_change(self) -> Optional[TeamsStatusEvent]:
        """
        Polls current status and returns a TeamsStatusEvent only if state has changed since previous poll.

        Returns:
            TeamsStatusEvent or None: The new event if a change occurred, or None if unchanged.
        """
        current = self.get_status()
        if self.last_event is None:
            self.last_event = current
            return current

        # Compare critical fields to detect state transitions
        changed = (
            current.status != self.last_event.status
            or current.in_call != self.last_event.in_call
            or current.mic_active != self.last_event.mic_active
            or current.camera_active != self.last_event.camera_active
            or current.is_running != self.last_event.is_running
            or current.is_locked != self.last_event.is_locked
        )

        if changed:
            self.last_event = current
            return current

        return None

