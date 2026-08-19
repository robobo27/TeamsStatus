# host/teams_detector.py - Local Microsoft Teams status & activity detector for Windows
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
    AVAILABLE = "Available"
    BUSY = "Busy"
    DO_NOT_DISTURB = "DoNotDisturb"
    BE_RIGHT_BACK = "BeRightBack"
    AWAY = "Away"
    OFFLINE = "Offline"
    UNKNOWN = "Unknown"


# Canonical status normalization mapping
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
    cleaned = raw.strip().lower()
    return STATUS_MAP.get(cleaned, TeamsAvailability.UNKNOWN)


@dataclass
class TeamsStatusEvent:
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
        return json.dumps(self.to_dict())


class WindowsProcessTracker:
    """Detects whether Microsoft Teams desktop processes are running using native Windows API."""

    TEAMS_EXECUTABLES = {"ms-teams.exe", "msteams.exe", "teams.exe"}

    @staticmethod
    def is_running() -> bool:
        TH32CS_SNAPPROCESS = 0x00000002

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
                ("szExeFile", ctypes.c_char * 260),
            ]

        h_snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h_snap == -1 or h_snap == 0xFFFFFFFFFFFFFFFF:
            return False

        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

        found = False
        try:
            if ctypes.windll.kernel32.Process32First(h_snap, ctypes.byref(pe)):
                while True:
                    exe = pe.szExeFile.decode("utf-8", errors="ignore").strip().lower()
                    if exe in WindowsProcessTracker.TEAMS_EXECUTABLES:
                        found = True
                        break
                    if not ctypes.windll.kernel32.Process32Next(h_snap, ctypes.byref(pe)):
                        break
        finally:
            ctypes.windll.kernel32.CloseHandle(h_snap)

        return found


class WindowsSessionTracker:
    """Checks whether the Windows workstation is currently locked or in a switch screen."""

    @staticmethod
    def is_locked() -> bool:
        DESKTOP_SWITCHDESKTOP = 0x0100
        h_desktop = ctypes.windll.user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if h_desktop:
            ctypes.windll.user32.CloseDesktop(h_desktop)
            return False
        return True


class WindowsHardwareTracker:
    """Checks Windows CapabilityAccessManager Registry for active microphone and webcam use by Teams."""

    REG_BASE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
    TEAMS_PACKAGES = ["MSTeams_8wekyb3d8bbwe", "Microsoft.Teams_8wekyb3d8bbwe"]

    @classmethod
    def _is_capability_in_use(cls, capability: str) -> bool:
        """capability: 'microphone' or 'webcam'"""
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

                    if start_time > 0 and (stop_time == 0 or start_time > stop_time):
                        return True
            except (FileNotFoundError, OSError):
                continue

        # Also check NonPackaged entries for classic or unpackaged Teams
        non_packaged_path = f"{cls.REG_BASE}\\{capability}\\NonPackaged"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, non_packaged_path) as root_key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(root_key, index)
                        index += 1
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
                        break
        except (FileNotFoundError, OSError):
            pass

        return False

    @classmethod
    def is_mic_active(cls) -> bool:
        return cls._is_capability_in_use("microphone")

    @classmethod
    def is_camera_active(cls) -> bool:
        return cls._is_capability_in_use("webcam")


class TeamsLogTailer:
    """Tails local Microsoft Teams log files incrementally with log rotation support."""

    ACTION_AVAILABILITY_PATTERN = re.compile(
        r"UserPresenceAction:\s*\{[^}]*availability:\s*([A-Za-z]+)",
        re.IGNORECASE,
    )

    GLOBAL_STATE_PATTERN = re.compile(
        r"UserDataGlobalState total number of users:\s*\d+((?:\s*\{[^}]+\})+)",
        re.IGNORECASE,
    )

    ITEM_AVAILABILITY_PATTERN = re.compile(
        r"availability:\s*([A-Za-z]+)",
        re.IGNORECASE,
    )

    FALLBACK_PATTERNS = [
        re.compile(r"Setting (?:the )?user status to ([A-Za-z]+)", re.IGNORECASE),
        re.compile(r"Status is ([A-Za-z]+)", re.IGNORECASE),
    ]

    MEETING_SIZE_PATTERN = re.compile(
        r"cross_cloud::meetingstore:\s*(?:global\s+state\s+)?meetings\s+size:\s*(\d+)",
        re.IGNORECASE,
    )

    def __init__(self, log_dir: Optional[str] = None):
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

        # Perform initial scan to seed availability
        self._initialize_tailer()

    def _get_latest_log_file(self) -> Optional[str]:
        if not os.path.isdir(self.log_dir):
            return None

        candidates = glob.glob(os.path.join(self.log_dir, "MSTeams_*.log"))
        if not candidates:
            candidates = glob.glob(os.path.join(self.log_dir, "*.log"))

        if not candidates:
            return None

        # Sort by modification time descending
        candidates.sort(key=os.path.getmtime, reverse=True)
        return candidates[0]

    def _initialize_tailer(self):
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
        # 1. Check for specific Action: UserPresenceAction
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

            # Prioritize active presence over Unknown
            if found_availabilities:
                self.last_availability = found_availabilities[-1]
                return

        # 3. Check fallback patterns
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
        """Polls for new log lines. Returns (availability, meeting_count)."""
        latest = self._get_latest_log_file()

        # Handle log file rotation
        if latest and latest != self.current_file:
            if self.current_file and os.path.isfile(self.current_file):
                self._read_incremental(self.current_file)
            self.current_file = latest
            self.file_pos = 0

        if self.current_file and os.path.isfile(self.current_file):
            self._read_incremental(self.current_file)

        return self.last_availability, self.meeting_count

    def _read_incremental(self, file_path: str):
        try:
            file_size = os.path.getsize(file_path)
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
    """Aggregates log tailing, hardware states, process status, and workstation state into unified events."""

    def __init__(self, log_dir: Optional[str] = None):
        self.log_tailer = TeamsLogTailer(log_dir)
        self.last_event: Optional[TeamsStatusEvent] = None

    def get_status(self) -> TeamsStatusEvent:
        is_running = WindowsProcessTracker.is_running()
        is_locked = WindowsSessionTracker.is_locked()
        mic_active = WindowsHardwareTracker.is_mic_active()
        camera_active = WindowsHardwareTracker.is_camera_active()

        availability, meeting_count = self.log_tailer.poll()
        in_meeting = meeting_count > 0
        in_call = in_meeting or mic_active

        # Compute effective status
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
        """Polls current status and returns a TeamsStatusEvent only if state has changed."""
        current = self.get_status()
        if self.last_event is None:
            self.last_event = current
            return current

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
