"""
Pytest configuration and common fixtures for the test suite.

This file provides common test fixtures and configuration that can be shared
across multiple test modules.
"""

import pytest
import os
import sys
from unittest.mock import MagicMock
from pathlib import Path

# Add the src directory to the Python path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Set up test environment variables
os.environ.setdefault('TESTING', 'true')


@pytest.fixture(scope="session")
def test_audio_dir():
    """Provide a test audio directory path."""
    return Path(__file__).parent / "test_audio_files"


@pytest.fixture(scope="session")
def mock_aws_credentials():
    """Provide mock AWS credentials for testing."""
    return {
        "region_name": "us-east-1",
        "aws_access_key_id": "test_key_id",
        "aws_secret_access_key": "test_secret_key",
        "bot_alias_id": "TESTALIAS"
    }


@pytest.fixture(scope="session")
def mock_aws_config_no_creds():
    """Provide mock AWS config without explicit credentials."""
    return {
        "region_name": "us-east-1",
        "bot_alias_id": "TESTALIAS"
    }


@pytest.fixture(scope="function")
def mock_boto3_session():
    """Provide a mock boto3 session for testing."""
    with pytest.MonkeyPatch().context() as m:
        mock_session = MagicMock()
        mock_session.client.side_effect = lambda service: {
            'lexv2-models': MagicMock(),
            'lexv2-runtime': MagicMock()
        }[service]
        
        m.setattr('boto3.Session', MagicMock(return_value=mock_session))
        yield mock_session


@pytest.fixture(scope="function")
def mock_lex_client():
    """Provide a mock Lex client for testing."""
    mock_client = MagicMock()
    mock_client.list_bots.return_value = {
        "botSummaries": [
            {"botId": "bot123", "botName": "TestBot"},
            {"botId": "bot456", "botName": "AnotherBot"},
            {"botId": "bot789", "botName": "BookingBot"}
        ]
    }
    return mock_client


@pytest.fixture(scope="function")
def mock_lex_runtime():
    """Provide a mock Lex runtime client for testing."""
    mock_runtime = MagicMock()
    return mock_runtime


@pytest.fixture(scope="function")
def mock_audio_stream():
    """Provide a mock audio stream for testing."""
    mock_stream = MagicMock()
    mock_stream.read.return_value = b"mock_audio_data"
    mock_stream.close.return_value = None
    return mock_stream


@pytest.fixture(scope="function")
def sample_conversation_id():
    """Provide a sample conversation ID for testing."""
    return "test_conv_12345"


@pytest.fixture(scope="function")
def sample_session_data():
    """Provide sample session data for testing."""
    return {
        "session_id": "session_123",
        "display_name": "aws_lex_connector: TestBot",
        "actual_bot_id": "bot123",
        "bot_name": "TestBot"
    }


@pytest.fixture(scope="function")
def sample_message_data():
    """Provide sample message data for testing."""
    return {
        "input_type": "audio",
        "audio_data": b"sample_audio_bytes",
        "conversation_id": "test_conv_12345",
        "virtual_agent_id": "aws_lex_connector: TestBot"
    }


@pytest.fixture(scope="function")
def sample_dtmf_data():
    """Provide sample DTMF data for testing."""
    return {
        "input_type": "dtmf",
        "dtmf_data": {
            "dtmf_events": [1, 2, 3]
        },
        "conversation_id": "test_conv_12345"
    }


@pytest.fixture(scope="function")
def mock_logger():
    """Provide a mock logger for testing."""
    return MagicMock()


# Cleanup fixtures
@pytest.fixture(scope="function", autouse=True)
def cleanup_test_files():
    """Clean up any test files created during testing."""
    yield
    # Cleanup logic can be added here if needed
    pass


# Test markers
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "aws: marks tests as requiring AWS integration"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
