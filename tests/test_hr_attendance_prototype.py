"""Safety and seed-data checks for the isolated HR attendance prototype."""

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototypes" / "hr-attendance"


class HRAttendancePrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((PROTOTYPE / "sample_data.json").read_text(encoding="utf-8"))
        cls.script = (PROTOTYPE / "app.js").read_text(encoding="utf-8")
        cls.html = (PROTOTYPE / "index.html").read_text(encoding="utf-8")

    def test_seed_data_is_synthetic_and_contains_no_media(self):
        metadata = self.data["metadata"]
        self.assertTrue(metadata["syntheticOnly"])
        self.assertFalse(metadata["cameraMediaIncluded"])
        self.assertEqual(metadata["gpsTestPoint"]["latitude"], 0.0)
        self.assertEqual(metadata["gpsTestPoint"]["longitude"], 0.0)
        self.assertIn("not an office", metadata["gpsTestPoint"]["label"])

    def test_seed_references_are_valid_and_unique(self):
        employees = self.data["employees"]
        schedules = self.data["schedules"]
        employee_ids = [item["employeeId"] for item in employees]
        schedule_ids = [item["scheduleId"] for item in schedules]
        self.assertEqual(len(employee_ids), len(set(employee_ids)))
        self.assertEqual(len(schedule_ids), len(set(schedule_ids)))
        self.assertTrue(set(item["scheduleId"] for item in employees) <= set(schedule_ids))
        self.assertTrue(set(item["employeeId"] for item in self.data["attendanceRecords"]) <= set(employee_ids))
        self.assertTrue(set(item["scheduleId"] for item in self.data["attendanceRecords"]) <= set(schedule_ids))

    def test_sensor_access_is_user_initiated_and_not_persisted(self):
        self.assertIn("navigator.geolocation.getCurrentPosition", self.script)
        self.assertIn("navigator.mediaDevices.getUserMedia", self.script)
        self.assertNotIn("watchPosition", self.script)
        for forbidden in ("localStorage", "sessionStorage", "sendBeacon", "XMLHttpRequest"):
            self.assertNotIn(forbidden, self.script)
        self.assertIn('id="gpsOptIn" type="checkbox"', self.html)
        self.assertIn('id="cameraOptIn" type="checkbox"', self.html)
        self.assertNotIn('id="gpsOptIn" type="checkbox" checked', self.html)
        self.assertNotIn('id="cameraOptIn" type="checkbox" checked', self.html)
        self.assertIn("audio: false", self.script)
        self.assertIn("imageStored: false", self.script)
        self.assertIn("faceRecognition: false", self.script)
        self.assertNotIn("toDataURL", self.script)
        self.assertNotIn("drawImage", self.script)


if __name__ == "__main__":
    unittest.main()
