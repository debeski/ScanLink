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
        mock_requests.post.return_value = Mock(ok=False, status_code=409)

        forwarded = protocol_handler.forward_protocol_command(
            {"action": "scan", "doc_id": "42", "callback_url": None}
        )

        self.assertTrue(forwarded)

    @patch.object(protocol_handler, "requests")
    def test_is_existing_instance_running_checks_health(self, mock_requests):
        mock_requests.get.return_value = Mock(ok=True)

        self.assertTrue(protocol_handler.is_existing_instance_running())


if __name__ == "__main__":
    unittest.main()
