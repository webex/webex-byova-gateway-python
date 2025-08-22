"""
Tests for the message handling functionality in the connector classes.
"""
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import os
from typing import Dict, Any

from src.connectors.local_audio_connector import LocalAudioConnector


class TestMessageHandling(unittest.TestCase):
    """Test message handling in the connector classes."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock config with required parameters
        self.config = {
            "agent_id": "test_agent",
            "audio_base_path": "audio",
            "record_caller_audio": True,
            "audio_recording": {
                "output_directory": "test_audio_recordings",
                "file_format": "wav",
                "silence_timeout_ms": 2000
            }
        }
        
        # Create a temporary directory for tests if needed
        os.makedirs("test_audio_recordings", exist_ok=True)
        
        # Initialize LocalAudioConnector
        self.connector = LocalAudioConnector(self.config)
        
        # Add a mock logger
        self.connector.logger = MagicMock()
        
        # Set up conversation ID for tests
        self.conversation_id = "test_conversation"

    def test_conversation_start_handling(self):
        """Test handling of conversation_start events."""
        message_data = {
            "input_type": "conversation_start",
            "conversation_id": self.conversation_id
        }
        
        response = list(self.connector.send_message(self.conversation_id, message_data))
        assert len(response) == 1
        # Check that the response is a silence message
        self.assertEqual(response[0]["message_type"], "silence")
        self.assertEqual(response[0]["conversation_id"], self.conversation_id)
        self.assertEqual(response[0]["audio_content"], b"")
        self.assertEqual(response[0]["text"], "")
        self.assertEqual(response[0]["agent_id"], "test_agent")

    def test_event_handling(self):
        """Test handling of event inputs."""
        message_data = {
            "input_type": "event",
            "event_data": {
                "name": "test_event"
            },
            "conversation_id": self.conversation_id
        }
        
        response = list(self.connector.send_message(self.conversation_id, message_data))
        assert len(response) == 1
        # Check that the response is a silence message
        self.assertEqual(response[0]["message_type"], "silence")
        
        # Check that the event was logged
        self.connector.logger.info.assert_any_call(f"Event for conversation {self.conversation_id}: test_event")

    @patch('src.connectors.local_audio_connector.LocalAudioConnector._process_audio_for_recording')
    def test_audio_handling(self, mock_process_audio):
        """Test handling of audio inputs."""
        message_data = {
            "input_type": "audio",
            "audio_data": b"test_audio_bytes",
            "conversation_id": self.conversation_id
        }
        
        response = list(self.connector.send_message(self.conversation_id, message_data))
        assert len(response) == 1
        # Check that _process_audio_for_recording was called
        mock_process_audio.assert_called_once_with(b"test_audio_bytes", self.conversation_id)
        
        # Check that the response is a silence message
        self.assertEqual(response[0]["message_type"], "silence")
        self.assertEqual(response[0]["conversation_id"], self.conversation_id)

    def test_dtmf_transfer_handling(self):
        """Test handling of DTMF inputs for transfer (digit 5)."""
        # Mock the audio converter
        self.connector._convert_audio_to_wxcc_format = MagicMock(return_value=b"audio_bytes")
        
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {
                "dtmf_events": [5]  # Digit 5 for transfer
            },
            "conversation_id": self.conversation_id
        }
        
        response = list(self.connector.send_message(self.conversation_id, message_data))
        assert len(response) == 1
        # Check that the response is a transfer message
        self.assertEqual(response[0]["message_type"], "transfer")
        self.assertEqual(response[0]["conversation_id"], self.conversation_id)
        self.assertEqual(response[0]["audio_content"], b"audio_bytes")
        self.assertIn("Transferring", response[0]["text"])

    def test_dtmf_goodbye_handling(self):
        """Test handling of DTMF inputs for goodbye (digit 6)."""
        # Mock the audio converter
        self.connector._convert_audio_to_wxcc_format = MagicMock(return_value=b"audio_bytes")
        
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {
                "dtmf_events": [6]  # Digit 6 for goodbye
            },
            "conversation_id": self.conversation_id
        }
        
        response = list(self.connector.send_message(self.conversation_id, message_data))
        assert len(response) == 1
        # Check that the response is a goodbye message
        self.assertEqual(response[0]["message_type"], "goodbye")
        self.assertEqual(response[0]["conversation_id"], self.conversation_id)
        self.assertEqual(response[0]["audio_content"], b"audio_bytes")
        self.assertIn("Goodbye", response[0]["text"])

    def test_unrecognized_input_handling(self):
        """Test handling of unrecognized input types."""
        message_data = {
            "input_type": "unknown_type",
            "conversation_id": self.conversation_id
        }
        
        response = list(self.connector.send_message(self.conversation_id, message_data))
        assert len(response) == 1
        # Check that the response is a silence message
        self.assertEqual(response[0]["message_type"], "silence")
        self.assertEqual(response[0]["conversation_id"], self.conversation_id)
        self.assertEqual(response[0]["audio_content"], b"")
        self.assertEqual(response[0]["text"], "")

    def tearDown(self):
        """Clean up after tests."""
        # Clean up any test resources if necessary
        pass


if __name__ == "__main__":
    unittest.main()
