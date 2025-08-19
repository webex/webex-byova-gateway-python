"""
Test the audio extraction functionality in the IVendorConnector and its subclasses.
"""
import base64
import os
import sys
import unittest
from pathlib import Path

# Add src directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.connectors.local_audio_connector import LocalAudioConnector


class TestAudioExtraction(unittest.TestCase):
    """Test the audio extraction functionality."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a test audio connector with config dict
        config = {
            "agent_id": "test_agent",
            "audio_base_path": str(Path(__file__).parent.parent / "audio"),
            "record_caller_audio": True,
            "audio_recording": {
                "output_dir": str(Path(__file__).parent.parent / "test_audio_recordings"),
            }
        }
        self.connector = LocalAudioConnector(config=config)
        self.conversation_id = "test_conversation_id"

    def test_extract_audio_data_bytes(self):
        """Test extracting audio data from bytes."""
        # Test with bytes
        test_audio = b'test audio bytes'
        result = self.connector.extract_audio_data(test_audio, self.conversation_id)
        self.assertEqual(result, test_audio)

    def test_extract_audio_data_string(self):
        """Test extracting audio data from string."""
        # Test with base64 string
        original_bytes = b'test audio bytes'
        base64_str = base64.b64encode(original_bytes).decode('utf-8')
        result = self.connector.extract_audio_data(base64_str, self.conversation_id)
        self.assertEqual(result, original_bytes)

    def test_extract_audio_data_dict(self):
        """Test extracting audio data from dictionary."""
        # Test with dictionary containing audio_data key
        test_audio = b'test audio bytes'
        audio_dict = {"audio_data": test_audio}
        result = self.connector.extract_audio_data(audio_dict, self.conversation_id)
        self.assertEqual(result, test_audio)

        # Test with dictionary containing alternative audio key
        audio_dict = {"caller_audio": test_audio}
        result = self.connector.extract_audio_data(audio_dict, self.conversation_id)
        self.assertEqual(result, test_audio)

    def test_process_audio_format(self):
        """Test processing audio format."""
        test_audio = b'test audio bytes'
        detected_encoding = "pcm_16bit"

        # Default implementation should return the input unchanged
        audio_bytes, encoding = self.connector.process_audio_format(
            test_audio, detected_encoding, self.conversation_id
        )
        self.assertEqual(audio_bytes, test_audio)
        self.assertEqual(encoding, detected_encoding)


if __name__ == "__main__":
    unittest.main()
