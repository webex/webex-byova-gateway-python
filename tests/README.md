# Test Suite Documentation

This directory contains the comprehensive test suite for the Webex BYOVA Gateway Python project.

## Overview

The test suite covers all major components of the system including:
- **AWS Lex Connector** - Tests for AWS Lex integration functionality
- **Audio Processing** - Tests for audio format conversion and processing
- **Message Handling** - Tests for message routing and processing
- **Core Functionality** - Tests for the main gateway functionality

## Test Structure

```
tests/
├── conftest.py                    # Pytest configuration and shared fixtures
├── test_aws_lex_connector.py     # AWS Lex connector unit tests
├── test_audio_extraction.py      # Audio processing unit tests
├── test_message_handling.py      # Message handling unit tests
└── README.md                     # This file
```

## Running Tests

### Prerequisites

1. **Virtual Environment**: Activate the project's virtual environment
   ```bash
   source venv/bin/activate
   ```

2. **Dependencies**: Ensure all test dependencies are installed
   ```bash
   pip install -r requirements.txt
   ```

### Running All Tests

Use the test runner script (recommended):
```bash
python run_tests.py
```

Or use pytest directly:
```bash
pytest tests/
```

### Running Specific Test Files

```bash
# Run AWS Lex connector tests only
python run_tests.py tests/test_aws_lex_connector.py

# Run audio processing tests only
python run_tests.py tests/test_audio_extraction.py

# Run message handling tests only
python run_tests.py tests/test_message_handling.py
```

### Running Specific Test Functions

```bash
# Run a specific test function
python run_tests.py tests/test_aws_lex_connector.py::TestAWSLexConnector::test_init_with_explicit_credentials

# Run tests matching a pattern
pytest -k "test_init" tests/
```

### Listing Available Tests

```bash
python run_tests.py --list
```

## Test Configuration

### pytest.ini
The main pytest configuration file that sets:
- Test discovery patterns
- Output formatting
- Warning filters
- Custom markers

### conftest.py
Contains shared fixtures and configuration that can be used across multiple test modules.

## Test Categories

### Unit Tests (Default)
- Test individual functions and methods in isolation
- Use mocks to isolate dependencies
- Fast execution
- Marked with `@pytest.mark.unit` (default)

### Integration Tests
- Test component interactions
- May require external services or databases
- Slower execution
- Marked with `@pytest.mark.integration`

### AWS Integration Tests
- Tests that require AWS services
- May incur costs
- Marked with `@pytest.mark.aws`

### Slow Tests
- Tests that take longer to execute
- Marked with `@pytest.mark.slow`

## Test Coverage

### AWS Lex Connector Tests
The `test_aws_lex_connector.py` file provides comprehensive coverage of:

- **Initialization and Configuration**
  - Constructor with explicit credentials
  - Constructor without credentials (uses default chain)
  - Configuration validation
  - AWS client setup

- **Bot Management**
  - Discovering available bots
  - Bot name to ID mapping
  - Caching behavior
  - Error handling for AWS API failures

- **Conversation Lifecycle**
  - Starting conversations
  - Managing sessions
  - Ending conversations
  - Session cleanup

- **Message Handling**
  - Audio input processing
  - DTMF input handling
  - Event handling
  - Conversation start events
  - Unrecognized input types

- **Error Handling**
  - AWS API errors
  - Network failures
  - Invalid bot configurations
  - Missing sessions

- **Audio Processing**
  - Audio format conversion
  - WxCC compatibility
  - Fallback mechanisms

### Audio Processing Tests
The `test_audio_extraction.py` file covers:

- Audio data extraction from various formats
- Base64 encoding/decoding
- Audio format processing
- Error handling for invalid audio data

### Message Handling Tests
The `test_message_handling.py` file covers:

- Message routing
- Event handling
- DTMF processing
- Audio input processing

## Mocking Strategy

The test suite uses extensive mocking to ensure:
- **Isolation**: Tests don't depend on external services
- **Speed**: Tests run quickly without network calls
- **Reliability**: Tests are not affected by external service changes
- **Cost Control**: No AWS charges during testing

### Key Mocks

- **boto3.Session**: Mocked to avoid real AWS connections
- **AWS Lex Clients**: Mocked to return predictable responses
- **Audio Streams**: Mocked to simulate audio data
- **Loggers**: Mocked to avoid log output during tests

## Adding New Tests

### Test File Structure
```python
"""
Tests for [Component Name].

This module tests [brief description of what is tested].
"""

import pytest
from unittest.mock import MagicMock, patch
from [module_path] import [Class/Function]

class Test[ClassName]:
    """Test suite for [ClassName]."""
    
    @pytest.fixture
    def [fixture_name](self):
        """Provide [description of fixture]."""
        # Setup code
        return fixture_data
    
    def test_[functionality_name](self, [fixtures]):
        """Test [description of what is being tested]."""
        # Arrange
        # Act
        # Assert
```

### Test Naming Convention
- Test files: `test_[module_name].py`
- Test classes: `Test[ClassName]`
- Test methods: `test_[description]`

### Assertion Patterns
```python
# Basic assertions
assert result == expected_value
assert "expected_text" in response["text"]
assert response["message_type"] == "success"

# Mock verifications
mock_function.assert_called_once_with(expected_args)
mock_logger.error.assert_called()
```

## Continuous Integration

The test suite is designed to run in CI/CD environments:
- No external dependencies required
- Fast execution (< 1 second for full suite)
- Deterministic results
- Clear error reporting

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure the virtual environment is activated and `src/` is in the Python path
2. **Mock Failures**: Check that mocks are properly configured and return expected values
3. **Test Isolation**: Ensure tests don't share state between runs

### Debug Mode

Run tests with verbose output:
```bash
pytest -v -s tests/
```

### Test Discovery Issues

If tests aren't being discovered:
```bash
# Check test collection
pytest --collect-only tests/

# Check Python path
python -c "import sys; print(sys.path)"
```

## Performance

- **Total Test Count**: 46 tests
- **Execution Time**: ~0.12 seconds
- **Memory Usage**: Minimal (mocked dependencies)
- **CPU Usage**: Low (no heavy computation)

## Contributing

When adding new tests:
1. Follow the existing patterns and conventions
2. Ensure tests are isolated and don't depend on external services
3. Use appropriate mocking strategies
4. Add comprehensive docstrings
5. Update this README if adding new test categories
