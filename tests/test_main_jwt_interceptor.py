"""
Unit tests for JWT interceptor creation in main.py

This module tests the strict error handling for JWT authentication
configuration and initialization.
"""

import logging

# Import the function we're testing
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Import after path is set
from main import create_jwt_interceptor


class TestCreateJWTInterceptor:
    """Test cases for create_jwt_interceptor function in main.py"""

    @pytest.fixture
    def logger(self):
        """Create a test logger."""
        return logging.getLogger("test")

    @pytest.fixture
    def valid_config(self):
        """Create a valid JWT configuration."""
        return {
            "jwt_validation": {
                "enabled": True,
                "enforce_validation": True,
                "datasource_url": "https://test-gateway.example.com:443",
                "datasource_schema_uuid": "5397013b-7920-4ffc-807c-e8a3e0a18f43",
                "cache_duration_minutes": 60,
            }
        }

    def test_jwt_enabled_missing_datasource_url_raises_valueerror(self, logger):
        """Test that missing datasource_url raises ValueError when JWT is enabled."""
        config = {
            "jwt_validation": {
                "enabled": True,
                "datasource_url": "",  # Empty/missing
            }
        }

        with pytest.raises(ValueError, match="datasource_url is not configured"):
            create_jwt_interceptor(config, logger)

    def test_jwt_disabled_missing_datasource_url_returns_none(self, logger):
        """Test that missing datasource_url returns None when JWT is disabled."""
        config = {
            "jwt_validation": {
                "enabled": False,
                "datasource_url": "",  # Empty
            }
        }

        result = create_jwt_interceptor(config, logger)
        assert result is None

    def test_jwt_enabled_interceptor_creation_fails_raises_runtime_error(
        self, logger, valid_config
    ):
        """Test that interceptor creation failure raises RuntimeError when JWT is enabled."""
        # Mock JWTValidator to raise an exception
        with patch("main.JWTValidator") as mock_validator:
            mock_validator.side_effect = Exception("Test error during initialization")

            with pytest.raises(
                RuntimeError,
                match="Failed to create JWT interceptor but JWT validation is enabled",
            ):
                create_jwt_interceptor(valid_config, logger)

    def test_jwt_disabled_interceptor_creation_fails_returns_none(self, logger):
        """Test that interceptor creation failure returns None when JWT is disabled."""
        config = {
            "jwt_validation": {
                "enabled": False,
                "datasource_url": "https://test.example.com:443",
            }
        }

        # Mock JWTValidator to raise an exception
        with patch("main.JWTValidator") as mock_validator:
            mock_validator.side_effect = Exception("Test error during initialization")

            result = create_jwt_interceptor(config, logger)
            assert result is None

    def test_jwt_enabled_valid_config_creates_interceptor(self, logger, valid_config):
        """Test that valid configuration creates interceptor successfully."""
        with patch("main.JWTValidator") as mock_validator, patch(
            "main.JWTAuthInterceptor"
        ) as mock_interceptor:
            # Set up mocks
            mock_validator_instance = Mock()
            mock_validator.return_value = mock_validator_instance

            mock_interceptor_instance = Mock()
            mock_interceptor.return_value = mock_interceptor_instance

            result = create_jwt_interceptor(valid_config, logger)

            # Verify interceptor was created
            assert result is mock_interceptor_instance

            # Verify validator was created with correct parameters
            mock_validator.assert_called_once_with(
                datasource_url="https://test-gateway.example.com:443",
                datasource_schema_uuid="5397013b-7920-4ffc-807c-e8a3e0a18f43",
                cache_duration_minutes=60,
            )

            # Verify interceptor was created with validator
            mock_interceptor.assert_called_once_with(
                jwt_validator=mock_validator_instance, enabled=True, enforce=True
            )

    def test_jwt_enabled_default_schema_uuid(self, logger):
        """Test that default schema UUID is used when not specified."""
        config = {
            "jwt_validation": {
                "enabled": True,
                "datasource_url": "https://test-gateway.example.com:443",
                # datasource_schema_uuid not specified
            }
        }

        with patch("main.JWTValidator") as mock_validator, patch(
            "main.JWTAuthInterceptor"
        ):
            create_jwt_interceptor(config, logger)

            # Verify default schema UUID was used
            call_kwargs = mock_validator.call_args[1]
            assert (
                call_kwargs["datasource_schema_uuid"]
                == "5397013b-7920-4ffc-807c-e8a3e0a18f43"
            )

    def test_jwt_enabled_custom_cache_duration(self, logger):
        """Test that custom cache duration is used."""
        config = {
            "jwt_validation": {
                "enabled": True,
                "datasource_url": "https://test-gateway.example.com:443",
                "cache_duration_minutes": 120,  # Custom value
            }
        }

        with patch("main.JWTValidator") as mock_validator, patch(
            "main.JWTAuthInterceptor"
        ):
            create_jwt_interceptor(config, logger)

            # Verify custom cache duration was used
            call_kwargs = mock_validator.call_args[1]
            assert call_kwargs["cache_duration_minutes"] == 120

    def test_jwt_enabled_enforce_false(self, logger, valid_config):
        """Test that enforce_validation: false is respected."""
        valid_config["jwt_validation"]["enforce_validation"] = False

        with patch("main.JWTValidator"), patch(
            "main.JWTAuthInterceptor"
        ) as mock_interceptor:
            create_jwt_interceptor(valid_config, logger)

            # Verify interceptor was created with enforce=False
            call_kwargs = mock_interceptor.call_args[1]
            assert call_kwargs["enforce"] is False

    def test_jwt_no_config_section_returns_none(self, logger):
        """Test that missing jwt_validation config section returns None."""
        config = {}  # No jwt_validation section

        result = create_jwt_interceptor(config, logger)
        assert result is None

    def test_jwt_enabled_not_specified_returns_none(self, logger):
        """Test that JWT validation returns None when enabled is not specified (backward compatibility)."""
        config = {
            "jwt_validation": {
                # enabled not specified - should return None for backward compatibility
                "datasource_url": "https://test-gateway.example.com:443",
            }
        }

        result = create_jwt_interceptor(config, logger)
        # When enabled is not specified, it defaults to False (get returns False if not present)
        assert result is None
