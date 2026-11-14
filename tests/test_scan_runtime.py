import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import uuid

import scan_runtime


class ScanRuntimeDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.scanner = MagicMock()
        self.scanner.return_value.scan_to_pdf.side_effect = (
            lambda *args, **kwargs: io.BytesIO(b"%PDF-1.4\n")
        )
        for target, replacement in (
            ("scan_runtime.ScannerManager", self.scanner),
            ("scan_runtime.tk.Tk", MagicMock()),
            ("scan_runtime.init_gui", MagicMock()),
        ):
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def prepared(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "request.json").write_text(
            json.dumps({"job_id": "job", "scan_timeout_seconds": 5})
        )
        return directory

    def test_injected_worker_directories_are_refused(self):
        outside = Path(".xclude/test-output/runtime") / uuid.uuid4().hex
        job_named_outside = outside / "scanlink-job-injected"
        temp_job = Path(tempfile.mkdtemp(prefix="scanlink-job-"))
        self.addCleanup(shutil.rmtree, temp_job, ignore_errors=True)
        other_temp = Path(tempfile.mkdtemp(prefix="not-scanlink-"))
        self.addCleanup(shutil.rmtree, other_temp, ignore_errors=True)
        for directory in (
            self.prepared(outside),
            self.prepared(job_named_outside),
            self.prepared(other_temp),
            os.path.join(temp_job, "..", other_temp.name),
            r"\\attacker.example\share\scanlink-job-x",
        ):
            with self.subTest(directory=str(directory)):
                self.assertNotEqual(scan_runtime.run_scan_job(str(directory)), 0)
                for name in ("state.json", "result.pdf"):
                    self.assertFalse(Path(directory, name).exists())
        self.scanner.return_value.scan_to_pdf.assert_not_called()

    def test_parent_created_job_directory_runs(self):
        directory = self.prepared(tempfile.mkdtemp(prefix="scanlink-job-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.assertEqual(scan_runtime.run_scan_job(str(directory)), 0)
        self.assertEqual((directory / "result.pdf").read_bytes(), b"%PDF-1.4\n")
        self.assertEqual(
            json.loads((directory / "state.json").read_text())["status"], "completed"
        )


if __name__ == "__main__":
    unittest.main()
