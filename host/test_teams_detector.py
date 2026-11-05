"""
host/test_teams_detector.py - Unit test suite for TeamsDetector, TeamsLogTailer, and normalization.

Test Coverage:
  1. `test_status_normalization`: Validates string-to-enum canonical mapping across casing and abbreviations.
  2. `test_log_tailer_initial_read`: Verifies initial log scan seeds user presence from `UserPresenceAction`.
  3. `test_log_tailer_incremental_append`: Tests streaming tailing of newly appended lines and meeting size tracking.
  4. `test_log_tailer_global_state_parsing`: Tests multi-user presence blocks from `UserDataGlobalState`.
  5. `test_log_tailer_rotation`: Tests detection and transition to newly created / rotated log files.
  6. `test_status_event_json_serialization`: Validates JSON schema formatting and dictionary conversion.
  7. `test_detector_state_logic`: Tests state synthesis and priority resolution via mocking of Windows APIs.
"""

import json
import os
import shutil
import tempfile
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

try:
    from host.teams_detector import (
        STATUS_MAP,
        StatusPriorityConfig,
        TeamsAvailability,
        TeamsDetector,
        TeamsLogTailer,
        TeamsStatusEvent,
        WindowsHardwareTracker,
        WindowsProcessTracker,
        WindowsSessionTracker,
        normalize_status,
    )
except ImportError:
    from teams_detector import (
        STATUS_MAP,
        StatusPriorityConfig,
        TeamsAvailability,
        TeamsDetector,
        TeamsLogTailer,
        TeamsStatusEvent,
        WindowsHardwareTracker,
        WindowsProcessTracker,
        WindowsSessionTracker,
        normalize_status,
    )


class TestTeamsDetector(unittest.TestCase):
    """
    Test fixture providing isolated sandbox directories and comprehensive verification of detector logic.
    """

    def setUp(self):
        """Creates a temporary isolated log directory for each test run."""
        self.test_dir = tempfile.mkdtemp(prefix="teams_test_logs_")

    def tearDown(self):
        """Cleans up the temporary log directory and any mock artifacts."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_status_normalization(self):
        """
        Verifies that various string formats (casing variations, synonyms, abbreviations)
        map correctly to canonical TeamsAvailability enum values.
        """
        self.assertEqual(normalize_status("Available"), TeamsAvailability.AVAILABLE)
        self.assertEqual(normalize_status("busy"), TeamsAvailability.BUSY)
        self.assertEqual(normalize_status("DoNotDisturb"), TeamsAvailability.DO_NOT_DISTURB)
        self.assertEqual(normalize_status("Do not disturb"), TeamsAvailability.DO_NOT_DISTURB)
        self.assertEqual(normalize_status("dnd"), TeamsAvailability.DO_NOT_DISTURB)
        self.assertEqual(normalize_status("Focusing"), TeamsAvailability.DO_NOT_DISTURB)
        self.assertEqual(normalize_status("Presenting"), TeamsAvailability.DO_NOT_DISTURB)
        self.assertEqual(normalize_status("BeRightBack"), TeamsAvailability.BE_RIGHT_BACK)
        self.assertEqual(normalize_status("Be right back"), TeamsAvailability.BE_RIGHT_BACK)
        self.assertEqual(normalize_status("away"), TeamsAvailability.AWAY)
        self.assertEqual(normalize_status("Offline"), TeamsAvailability.OFFLINE)
        self.assertEqual(normalize_status("PresenceUnknown"), TeamsAvailability.UNKNOWN)
        self.assertEqual(normalize_status("UnknownRandom"), TeamsAvailability.UNKNOWN)

    def test_log_tailer_partial_line_and_badge_parsing(self):
        """
        Verifies that:
          1. TaskbarModule ShowBadge / SetBadge lines (including multi-word 'Do not disturb') are parsed.
          2. Partial lines flushed mid-word without a trailing newline (due to Teams' 8 KB stdio buffer)
             are held until the remainder of the line and newline are flushed.
        """
        log_file = os.path.join(self.test_dir, "MSTeams_2026-08-19_01-00-00.00.log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(
                "2026-08-19T10:00:00.000 <DBG> native_modules::TaskbarModule: "
                "ShowBadge New Badge:NumericBadge{0}, overlay: 0 items, status Do not disturb\n"
            )

        tailer = TeamsLogTailer(log_dir=self.test_dir)
        self.assertEqual(tailer.poll()[0], TeamsAvailability.DO_NOT_DISTURB)

        # Simulate an 8 KB buffer flush that cuts a UserPresenceAction line in half (no trailing newline)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(
                "2026-08-19T10:01:00.000 <INFO> native_modules::UserDataCrossCloudModule: "
                "Received Action: UserPresenceAction: {cloud_context: https://teams.live.com, availa"
            )

        # Polling while the line is incomplete must keep the previous status and not advance past the fragment
        self.assertEqual(tailer.poll()[0], TeamsAvailability.DO_NOT_DISTURB)

        # Now flush the rest of the split line with a newline
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("bility: BeRightBack}\n")

        self.assertEqual(tailer.poll()[0], TeamsAvailability.BE_RIGHT_BACK)

    def test_log_tailer_initial_read(self):
        """
        Verifies that when TeamsLogTailer initializes, it reads the pre-existing
        log file to discover the most recent presence state.
        """
        log_file = os.path.join(self.test_dir, "MSTeams_2026-08-19_01-00-00.00.log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("2026-08-19T10:00:00.000 <INFO> boot: starting...\n")
            f.write("2026-08-19T10:00:01.000 <INFO> native_modules::UserDataCrossCloudModule: Received Action: UserPresenceAction: {cloud_context: https://teams.live.com, availability: Busy}\n")

        tailer = TeamsLogTailer(log_dir=self.test_dir)
        availability, meeting_count = tailer.poll()

        self.assertEqual(availability, TeamsAvailability.BUSY)
        self.assertEqual(meeting_count, 0)

    def test_log_tailer_incremental_append(self):
        """
        Verifies that after the initial scan, subsequent poll() calls process
        only newly appended lines without replaying older lines.
        """
        log_file = os.path.join(self.test_dir, "MSTeams_2026-08-19_01-00-00.00.log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("2026-08-19T10:00:00.000 <INFO> native_modules::UserDataCrossCloudModule: Received Action: UserPresenceAction: {cloud_context: https://teams.live.com, availability: Available}\n")

        tailer = TeamsLogTailer(log_dir=self.test_dir)
        self.assertEqual(tailer.poll()[0], TeamsAvailability.AVAILABLE)

        # Simulate Teams appending new events to the active log file
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-08-19T10:05:00.000 <INFO> native_modules::UserDataCrossCloudModule: Received Action: UserPresenceAction: {cloud_context: https://teams.live.com, availability: DoNotDisturb}\n")
            f.write("2026-08-19T10:05:01.000 <DBG> cross_cloud::meetingstore: global state meetings size: 1\n")

        availability, meeting_count = tailer.poll()
        self.assertEqual(availability, TeamsAvailability.DO_NOT_DISTURB)
        self.assertEqual(meeting_count, 1)

    def test_log_tailer_global_state_parsing(self):
        """
        Verifies extraction of availability from multi-user UserDataGlobalState blocks.
        """
        log_file = os.path.join(self.test_dir, "MSTeams_2026-08-19_01-00-00.00.log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("2026-08-19T10:00:00.000 <INFO> native_modules::UserDataCrossCloudModule: BroadcastGlobalState: New Global State Event: UserDataGlobalState total number of users: 2 { availability: PresenceUnknown, unread notification count: 0 } { availability: Away, unread notification count: 0 }\n")

        tailer = TeamsLogTailer(log_dir=self.test_dir)
        availability, _ = tailer.poll()
        self.assertEqual(availability, TeamsAvailability.AWAY)

    def test_log_tailer_rotation(self):
        """
        Verifies that when Teams starts writing to a new log file (e.g. after restart),
        TeamsLogTailer detects the newer file and switches to tailing it.
        """
        log1 = os.path.join(self.test_dir, "MSTeams_2026-08-19_01-00-00.00.log")
        with open(log1, "w", encoding="utf-8") as f:
            f.write("2026-08-19T10:00:00.000 <INFO> native_modules::UserDataCrossCloudModule: Received Action: UserPresenceAction: {cloud_context: https://teams.live.com, availability: Available}\n")

        tailer = TeamsLogTailer(log_dir=self.test_dir)
        self.assertEqual(tailer.poll()[0], TeamsAvailability.AVAILABLE)

        time.sleep(0.05)
        # Create a newer rotated log file with a later timestamp
        log2 = os.path.join(self.test_dir, "MSTeams_2026-08-19_02-00-00.00.log")
        with open(log2, "w", encoding="utf-8") as f:
            f.write("2026-08-19T11:00:00.000 <INFO> native_modules::UserDataCrossCloudModule: Received Action: UserPresenceAction: {cloud_context: https://teams.live.com, availability: Busy}\n")

        availability, _ = tailer.poll()
        self.assertEqual(availability, TeamsAvailability.BUSY)
        self.assertEqual(tailer.current_file, log2)

    def test_status_event_json_serialization(self):
        """
        Verifies that TeamsStatusEvent serializes cleanly to a dictionary and valid JSON string.
        """
        event = TeamsStatusEvent(
            status="Busy",
            availability="Busy",
            in_call=True,
            in_meeting=True,
            mic_active=True,
            camera_active=False,
            is_running=True,
            is_locked=False,
            timestamp="2026-08-19T12:00:00+00:00",
        )

        data = event.to_dict()
        self.assertEqual(data["type"], "teams_status")
        self.assertEqual(data["status"], "Busy")
        self.assertTrue(data["in_call"])

        json_str = event.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["status"], "Busy")
        self.assertTrue(parsed["mic_active"])
        self.assertFalse(parsed["camera_active"])

    def test_detector_state_logic(self):
        """
        Verifies the precedence rules of TeamsDetector by mocking Windows API trackers:
          - Running + Unlocked + Available (even with calendar meetings in meetingstore) -> Available
          - Running + Unlocked + Busy (mic & cam off) -> Busy
          - Running + Unlocked + Busy + Mic on -> InACall
          - Running + Locked -> Away
          - Not running -> NotRunning
        """
        log_file = os.path.join(self.test_dir, "MSTeams_2026-08-19_01-00-00.00.log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("2026-08-19T10:00:00.000 <INFO> native_modules::UserDataCrossCloudModule: Received Action: UserPresenceAction: {cloud_context: https://teams.microsoft.com, availability: Available}\n")
            f.write("2026-08-19T10:00:01.000 <DBG> cross_cloud::meetingstore: meetings size: 3\n")

        detector = TeamsDetector(log_dir=self.test_dir)

        mod_name = "host.teams_detector" if "host.teams_detector" in sys.modules else "teams_detector"
        with patch(f"{mod_name}.WindowsProcessTracker.is_running") as mock_running, \
             patch(f"{mod_name}.WindowsSessionTracker.is_locked") as mock_locked, \
             patch(f"{mod_name}.WindowsHardwareTracker.is_mic_active") as mock_mic, \
             patch(f"{mod_name}.WindowsHardwareTracker.is_camera_active") as mock_cam:

            # 1. Normal Available state on corporate Teams (even with meetingstore > 0 or stray mic):
            mock_running.return_value = True
            mock_locked.return_value = False
            mock_mic.return_value = False
            mock_cam.return_value = False

            status = detector.get_status()
            self.assertEqual(status.status, "Available")
            self.assertFalse(status.in_call)
            self.assertEqual(status.log_source, "UserPresenceAction")
            self.assertEqual(status.meeting_count, 3)
            self.assertEqual(status.status_source, "Teams Log (UserPresenceAction: Available)")

            # Even if mic_active reports True while presence is explicitly Available,
            # Available must not be falsely overridden to InACall
            mock_mic.return_value = True
            status = detector.get_status()
            self.assertEqual(status.status, "Available")
            self.assertFalse(status.in_call)
            self.assertEqual(status.status_source, "Teams Log (UserPresenceAction: Available)")

            # 2. Busy state (not in a call: mic & cam inactive)
            mock_mic.return_value = False
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("2026-08-19T10:02:00.000 <INFO> native_modules::UserDataCrossCloudModule: Received Action: UserPresenceAction: {cloud_context: https://teams.microsoft.com, availability: Busy}\n")
            status = detector.get_status()
            self.assertEqual(status.status, "Busy")
            self.assertFalse(status.in_call)
            self.assertEqual(status.status_source, "Teams Log (UserPresenceAction: Busy)")

            # 3. In Call state: User is Busy and microphone becomes active during a voice/video call
            mock_mic.return_value = True
            status = detector.get_status()
            self.assertEqual(status.status, "InACall")
            self.assertTrue(status.in_call)
            self.assertIn("Microphone", status.status_source)
            self.assertIn("Meeting Size (3)", status.status_source)

            # 4. Workstation Locked: User locks their computer (Win+L)
            mock_mic.return_value = False
            mock_locked.return_value = True
            status = detector.get_status()
            self.assertEqual(status.status, "Away")
            self.assertTrue(status.is_locked)
            self.assertEqual(status.status_source, "Session Monitor (Workstation locked)")

            # 5. Teams closed: Application terminated
            mock_locked.return_value = False
            mock_running.return_value = False
            status = detector.get_status()
            self.assertEqual(status.status, "NotRunning")
            self.assertFalse(status.is_running)
            self.assertEqual(status.status_source, "Process Monitor (Teams not running)")

    def test_custom_priority_and_signal_toggles(self):
        """
        Verifies user-configurable taskbar priority reordering, presets, and signal toggling:
          - Moving `microphone` above `teams_log` (or applying 'hardware_first' preset) allows
            active mic to override 'Available' -> 'InACall'.
          - Applying 'log_only' preset ignores mic/camera/meeting_size so 'Busy' remains 'Busy'.
          - Enabling `meeting_size` allows meeting_count > 0 to promote 'Busy' -> 'InACall'.
        """
        log_file = os.path.join(self.test_dir, "MSTeams_2026-08-19_01-00-00.00.log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(
                "2026-08-19T10:00:00.000 <INFO> native_modules::UserDataCrossCloudModule: "
                "Received Action: UserPresenceAction: {cloud_context: https://teams.microsoft.com, availability: Available}\n"
            )
            f.write("2026-08-19T10:00:01.000 <DBG> cross_cloud::meetingstore: meetings size: 2\n")

        cfg = StatusPriorityConfig()
        detector = TeamsDetector(log_dir=self.test_dir, priority_config=cfg)

        mod_name = "host.teams_detector" if "host.teams_detector" in sys.modules else "teams_detector"
        with patch(f"{mod_name}.WindowsProcessTracker.is_running") as mock_running, \
             patch(f"{mod_name}.WindowsSessionTracker.is_locked") as mock_locked, \
             patch(f"{mod_name}.WindowsHardwareTracker.is_mic_active") as mock_mic, \
             patch(f"{mod_name}.WindowsHardwareTracker.is_camera_active") as mock_cam:

            mock_running.return_value = True
            mock_locked.return_value = False
            mock_mic.return_value = True
            mock_cam.return_value = False

            # 1. Default ('corporate_safe'): teams_log is above microphone -> Available wins
            self.assertEqual(cfg.get_active_preset(), "corporate_safe")
            status = detector.get_status()
            self.assertEqual(status.status, "Available")
            self.assertFalse(status.in_call)

            # 2. Move 'microphone' above 'teams_log': active mic now overrides Available -> InACall
            cfg.move_up("microphone")
            self.assertIsNone(cfg.get_active_preset())
            status = detector.get_status()
            self.assertEqual(status.status, "InACall")
            self.assertTrue(status.in_call)
            self.assertIn("Microphone", status.status_source)

            # 3. Disable 'microphone' toggle: falls back to teams_log ('Available')
            cfg.toggle("microphone")
            status = detector.get_status()
            self.assertEqual(status.status, "Available")
            self.assertFalse(status.in_call)

            # 4. Log changes to Busy; apply 'log_only' preset -> stays Busy even with mic_active=True
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(
                    "2026-08-19T10:05:00.000 <INFO> native_modules::UserDataCrossCloudModule: "
                    "Received Action: UserPresenceAction: {cloud_context: https://teams.microsoft.com, availability: Busy}\n"
                )
            cfg.apply_preset("log_only")
            self.assertEqual(cfg.get_active_preset(), "log_only")
            status = detector.get_status()
            self.assertEqual(status.status, "Busy")
            self.assertFalse(status.in_call)

            # 5. Apply 'strict' preset (enables meeting_size) with mic off -> meeting_size (2) promotes Busy -> InACall
            mock_mic.return_value = False
            cfg.apply_preset("strict")
            self.assertEqual(cfg.get_active_preset(), "strict")
            status = detector.get_status()
            self.assertEqual(status.status, "InACall")
            self.assertTrue(status.in_call)
            self.assertIn("Meeting Size (2)", status.status_source)

            # 6. Serialization round-trip & reset_defaults
            restored = StatusPriorityConfig.from_dict(cfg.to_dict())
            self.assertEqual(restored.get_active_preset(), "strict")
            cfg.reset_defaults()
            self.assertEqual(cfg.get_active_preset(), "corporate_safe")


if __name__ == "__main__":
    unittest.main()

