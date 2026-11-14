import unittest
from unittest.mock import Mock, patch

import protocol_handler


class ProtocolHandlerTests(unittest.TestCase):
    def test_parse_protocol_url_extracts_known_fields(self):
        command = protocol_handler.parse_protocol_url(
            "scanlink://scan?docId=42&callback=https://example.com/upload"
        )

        self.assertEqual(command["action"], "scan")
        self.assertEqual(command["doc_id"], "42")
        self.assertEqual(command["callback_url"], "https://example.com/upload")

    @patch.object(protocol_handler, "requests")
    def test_forward_protocol_command_accepts_busy_response(self, mock_requests):
        mock_requests.post.return_value = Mock(
            ok=False,
            status_code=409,
            json=Mock(return_value={"error": {"code": "busy", "message": "Busy"}}),
        )

        forwarded = protocol_handler.forward_protocol_command(
            {"action": "scan", "doc_id": "42", "callback_url": None}
        )

        self.assertTrue(forwarded)

    @patch.object(protocol_handler, "requests")
    def test_is_existing_instance_running_checks_health(self, mock_requests):
        mock_requests.get.return_value = Mock(
            ok=True,
            json=Mock(
                return_value={"status": "ok", "version": "0.8.0", "twain_available": True}
            ),
        )

        self.assertTrue(protocol_handler.is_existing_instance_running())

    @patch.object(protocol_handler, "requests")
    def test_another_program_on_the_port_is_not_scanlink(self, mock_requests):
        mock_requests.RequestException = Exception
        for payload in (ValueError("not json"), {"status": "ok"}, ["ok"]):
            with self.subTest(payload=payload):
                foreign = Mock(ok=True, status_code=200)
                if isinstance(payload, Exception):
                    foreign.json.side_effect = payload
                else:
                    foreign.json.return_value = payload
                mock_requests.get.return_value = foreign
                mock_requests.post.return_value = foreign
                self.assertFalse(protocol_handler.is_existing_instance_running())
                self.assertFalse(
                    protocol_handler.forward_protocol_command({"action": "scan"})
                )

    @patch.object(protocol_handler, "requests")
    def test_forward_protocol_command_accepts_a_queued_job(self, mock_requests):
        mock_requests.post.return_value = Mock(
            ok=True,
            status_code=202,
            json=Mock(return_value={"job_id": "job-1", "status": "queued"}),
        )

        self.assertTrue(protocol_handler.forward_protocol_command({"action": "scan"}))

    def test_parse_failures_are_logged_on_one_line(self):
        with self.assertLogs("ScanLink", level="DEBUG") as captured:
            self.assertIsNone(
                protocol_handler.parse_protocol_url(
                    "scanlink://[\n2026-11-14 09:00:00,000 - INFO - forged"
                )
            )
            protocol_handler.parse_protocol_url("scanlink://scan?docId=a%0D%0Aforged")
        for line in captured.output:
            self.assertNotIn("\n", line)
            self.assertNotIn("\r", line)


if __name__ == "__main__":
    unittest.main()
