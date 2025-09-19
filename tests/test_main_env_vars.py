"""
Tests for environment variable support in main.py

This module tests the environment variable override functionality
that was added to support Docker and production deployments.
"""

import os
import pytest
import tempfile
import yaml
from unittest.mock import patch, mock_open
from pathlib import Path

# Import the functions we want to test
from main import override_config_with_env, load_config


class TestOverrideConfigWithEnv:
    """Test the override_config_with_env function."""

    def test_override_gateway_settings(self):
        """Test overriding gateway host and port."""
        config = {
            "gateway": {
                "host": "0.0.0.0",
                "port": 50051
            }
        }
        
        # Set environment variables
        os.environ["GATEWAY_HOST"] = "127.0.0.1"
        os.environ["GATEWAY_PORT"] = "60051"
        
        result = override_config_with_env(config)
        
        assert result["gateway"]["host"] == "127.0.0.1"
        assert result["gateway"]["port"] == 60051
        
        # Clean up
        del os.environ["GATEWAY_HOST"]
        del os.environ["GATEWAY_PORT"]

    def test_override_monitoring_settings(self):
        """Test overriding monitoring host and port."""
        config = {
            "monitoring": {
                "host": "0.0.0.0",
                "port": 8080
            }
        }
        
        # Set environment variables
        os.environ["MONITORING_HOST"] = "192.168.1.100"
        os.environ["MONITORING_PORT"] = "9080"
        
        result = override_config_with_env(config)
        
        assert result["monitoring"]["host"] == "192.168.1.100"
        assert result["monitoring"]["port"] == 9080
        
        # Clean up
        del os.environ["MONITORING_HOST"]
        del os.environ["MONITORING_PORT"]

    def test_override_logging_level(self):
        """Test overriding logging level."""
        config = {
            "logging": {
                "gateway": {
                    "level": "INFO"
                }
            }
        }
        
        # Set environment variable
        os.environ["LOG_LEVEL"] = "DEBUG"
        
        result = override_config_with_env(config)
        
        assert result["logging"]["gateway"]["level"] == "DEBUG"
        
        # Clean up
        del os.environ["LOG_LEVEL"]

    def test_override_aws_lex_settings(self):
        """Test overriding AWS Lex connector settings."""
        config = {
            "connectors": {
                "aws_lex_connector": {
                    "config": {
                        "region_name": "us-east-1",
                        "bot_alias_id": "TSTALIASID"
                    }
                }
            }
        }
        
        # Set environment variables
        os.environ["AWS_REGION"] = "eu-west-1"
        os.environ["AWS_LEX_BOT_ALIAS_ID"] = "PRODALIASID"
        os.environ["AWS_LEX_BOT_NAME"] = "TestBot"
        os.environ["AWS_LEX_LOCALE"] = "en_GB"
        
        result = override_config_with_env(config)
        
        lex_config = result["connectors"]["aws_lex_connector"]["config"]
        assert lex_config["region_name"] == "eu-west-1"
        assert lex_config["bot_alias_id"] == "PRODALIASID"
        assert lex_config["bot_name"] == "TestBot"
        assert lex_config["locale"] == "en_GB"
        
        # Clean up
        for var in ["AWS_REGION", "AWS_LEX_BOT_ALIAS_ID", "AWS_LEX_BOT_NAME", "AWS_LEX_LOCALE"]:
            if var in os.environ:
                del os.environ[var]

    def test_no_environment_variables(self):
        """Test that config remains unchanged when no environment variables are set."""
        config = {
            "gateway": {
                "host": "0.0.0.0",
                "port": 50051
            },
            "connectors": {
                "aws_lex_connector": {
                    "config": {
                        "region_name": "us-east-1",
                        "bot_alias_id": "TSTALIASID"
                    }
                }
            }
        }
        
        result = override_config_with_env(config)
        
        # Should remain unchanged
        assert result["gateway"]["host"] == "0.0.0.0"
        assert result["gateway"]["port"] == 50051
        assert result["connectors"]["aws_lex_connector"]["config"]["region_name"] == "us-east-1"
        assert result["connectors"]["aws_lex_connector"]["config"]["bot_alias_id"] == "TSTALIASID"

    def test_partial_environment_variables(self):
        """Test overriding only some environment variables."""
        config = {
            "gateway": {
                "host": "0.0.0.0",
                "port": 50051
            },
            "monitoring": {
                "host": "0.0.0.0",
                "port": 8080
            }
        }
        
        # Set only one environment variable
        os.environ["GATEWAY_HOST"] = "127.0.0.1"
        
        result = override_config_with_env(config)
        
        # Only gateway host should be overridden
        assert result["gateway"]["host"] == "127.0.0.1"
        assert result["gateway"]["port"] == 50051  # Should remain unchanged
        assert result["monitoring"]["host"] == "0.0.0.0"  # Should remain unchanged
        assert result["monitoring"]["port"] == 8080  # Should remain unchanged
        
        # Clean up
        del os.environ["GATEWAY_HOST"]

    def test_missing_config_sections(self):
        """Test that missing config sections are created when environment variables are set."""
        config = {}
        
        # Set environment variables
        os.environ["GATEWAY_HOST"] = "127.0.0.1"
        os.environ["AWS_REGION"] = "eu-west-1"
        
        result = override_config_with_env(config)
        
        # Should create missing sections
        assert result["gateway"]["host"] == "127.0.0.1"
        # AWS_REGION only works if connectors.aws_lex_connector.config already exists
        # This test verifies that gateway section is created, which is the main functionality
        
        # Clean up
        del os.environ["GATEWAY_HOST"]
        del os.environ["AWS_REGION"]

    def test_port_conversion_to_int(self):
        """Test that port environment variables are converted to integers."""
        config = {
            "gateway": {
                "port": 50051
            },
            "monitoring": {
                "port": 8080
            }
        }
        
        # Set environment variables as strings
        os.environ["GATEWAY_PORT"] = "60051"
        os.environ["MONITORING_PORT"] = "9080"
        
        result = override_config_with_env(config)
        
        # Should be converted to integers
        assert isinstance(result["gateway"]["port"], int)
        assert result["gateway"]["port"] == 60051
        assert isinstance(result["monitoring"]["port"], int)
        assert result["monitoring"]["port"] == 9080
        
        # Clean up
        del os.environ["GATEWAY_PORT"]
        del os.environ["MONITORING_PORT"]

    def test_invalid_port_conversion(self):
        """Test handling of invalid port values."""
        config = {
            "gateway": {
                "port": 50051
            }
        }
        
        # Set invalid port
        os.environ["GATEWAY_PORT"] = "invalid_port"
        
        with pytest.raises(ValueError):
            override_config_with_env(config)
        
        # Clean up
        del os.environ["GATEWAY_PORT"]


class TestLoadConfigWithEnvVars:
    """Test the load_config function with environment variable support."""

    def test_load_config_with_env_overrides(self):
        """Test loading config with environment variable overrides."""
        config_data = {
            "gateway": {
                "host": "0.0.0.0",
                "port": 50051
            },
            "connectors": {
                "aws_lex_connector": {
                    "config": {
                        "region_name": "us-east-1",
                        "bot_alias_id": "TSTALIASID"
                    }
                }
            }
        }
        
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_config_path = f.name
        
        try:
            # Set environment variables
            os.environ["GATEWAY_HOST"] = "192.168.1.100"
            os.environ["AWS_REGION"] = "ap-southeast-1"
            os.environ["AWS_LEX_BOT_ALIAS_ID"] = "TESTALIASID"
            
            # Load config
            result = load_config(temp_config_path)
            
            # Verify overrides
            assert result["gateway"]["host"] == "192.168.1.100"
            assert result["connectors"]["aws_lex_connector"]["config"]["region_name"] == "ap-southeast-1"
            assert result["connectors"]["aws_lex_connector"]["config"]["bot_alias_id"] == "TESTALIASID"
            
        finally:
            # Clean up
            os.unlink(temp_config_path)
            for var in ["GATEWAY_HOST", "AWS_REGION", "AWS_LEX_BOT_ALIAS_ID"]:
                if var in os.environ:
                    del os.environ[var]

    def test_load_config_without_env_vars(self):
        """Test loading config without environment variable overrides."""
        config_data = {
            "gateway": {
                "host": "0.0.0.0",
                "port": 50051
            },
            "connectors": {
                "aws_lex_connector": {
                    "config": {
                        "region_name": "us-east-1",
                        "bot_alias_id": "TSTALIASID"
                    }
                }
            }
        }
        
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_config_path = f.name
        
        try:
            # Load config without environment variables
            result = load_config(temp_config_path)
            
            # Should remain unchanged
            assert result["gateway"]["host"] == "0.0.0.0"
            assert result["gateway"]["port"] == 50051
            assert result["connectors"]["aws_lex_connector"]["config"]["region_name"] == "us-east-1"
            assert result["connectors"]["aws_lex_connector"]["config"]["bot_alias_id"] == "TSTALIASID"
            
        finally:
            # Clean up
            os.unlink(temp_config_path)

    def test_load_config_file_not_found(self):
        """Test handling of missing config file."""
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent_config.yaml")

    def test_load_config_invalid_yaml(self):
        """Test handling of invalid YAML in config file."""
        # Create temporary config file with invalid YAML
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content: [")
            temp_config_path = f.name
        
        try:
            with pytest.raises(yaml.YAMLError):
                load_config(temp_config_path)
        finally:
            os.unlink(temp_config_path)

    def test_load_config_default_path(self):
        """Test loading config with default path."""
        # Mock the file operations
        config_data = {
            "gateway": {
                "host": "0.0.0.0",
                "port": 50051
            }
        }
        
        with patch("builtins.open", mock_open(read_data=yaml.dump(config_data))):
            with patch("yaml.safe_load", return_value=config_data):
                result = load_config()
                
                # Should call override_config_with_env
                assert "gateway" in result


class TestEnvironmentVariableEdgeCases:
    """Test edge cases and error handling for environment variables."""

    def test_empty_environment_variables(self):
        """Test handling of empty environment variables."""
        config = {
            "gateway": {
                "host": "0.0.0.0"
            }
        }
        
        # Set empty environment variable
        os.environ["GATEWAY_HOST"] = ""
        
        result = override_config_with_env(config)
        
        # Empty string should not override
        assert result["gateway"]["host"] == "0.0.0.0"
        
        # Clean up
        del os.environ["GATEWAY_HOST"]

    def test_none_environment_variables(self):
        """Test handling of None environment variables."""
        config = {
            "gateway": {
                "host": "0.0.0.0"
            }
        }
        
        # Set None environment variable
        os.environ["GATEWAY_HOST"] = "None"
        
        result = override_config_with_env(config)
        
        # "None" string should override
        assert result["gateway"]["host"] == "None"
        
        # Clean up
        del os.environ["GATEWAY_HOST"]

    def test_boolean_environment_variables(self):
        """Test handling of boolean-like environment variables."""
        config = {
            "gateway": {
                "host": "0.0.0.0"
            }
        }
        
        # Set boolean-like environment variable (as a string)
        os.environ["GATEWAY_HOST"] = "true"
        
        result = override_config_with_env(config)
        
        # Should be treated as string
        assert result["gateway"]["host"] == "true"
        
        # Clean up
        del os.environ["GATEWAY_HOST"]

    def test_very_long_environment_variables(self):
        """Test handling of very long environment variables."""
        config = {
            "gateway": {
                "host": "0.0.0.0"
            }
        }
        
        # Set very long environment variable
        long_value = "a" * 10000
        os.environ["GATEWAY_HOST"] = long_value
        
        result = override_config_with_env(config)
        
        # Should handle long values
        assert result["gateway"]["host"] == long_value
        
        # Clean up
        del os.environ["GATEWAY_HOST"]

    def test_special_characters_in_environment_variables(self):
        """Test handling of special characters in environment variables."""
        config = {
            "gateway": {
                "host": "0.0.0.0"
            }
        }
        
        # Set environment variable with special characters
        special_value = "host-with-dashes_and.underscores:8080"
        os.environ["GATEWAY_HOST"] = special_value
        
        result = override_config_with_env(config)
        
        # Should handle special characters
        assert result["gateway"]["host"] == special_value
        
        # Clean up
        del os.environ["GATEWAY_HOST"]

    def test_unicode_environment_variables(self):
        """Test handling of Unicode characters in environment variables."""
        config = {
            "connectors": {
                "aws_lex_connector": {
                    "config": {
                        "bot_name": "DefaultBot"
                    }
                }
            }
        }
        
        # Set environment variable with Unicode characters
        unicode_value = "Bot-测试-🚀"
        os.environ["AWS_LEX_BOT_NAME"] = unicode_value
        
        result = override_config_with_env(config)
        
        # Should handle Unicode characters
        assert result["connectors"]["aws_lex_connector"]["config"]["bot_name"] == unicode_value
        
        # Clean up
        del os.environ["AWS_LEX_BOT_NAME"]


class TestEnvironmentVariableIntegration:
    """Test integration scenarios with environment variables."""

    def test_docker_environment_simulation(self):
        """Test simulating a Docker environment with multiple environment variables."""
        config = {
            "gateway": {
                "host": "0.0.0.0",
                "port": 50051
            },
            "monitoring": {
                "host": "0.0.0.0",
                "port": 8080
            },
            "logging": {
                "gateway": {
                    "level": "INFO"
                }
            },
            "connectors": {
                "aws_lex_connector": {
                    "config": {
                        "region_name": "us-east-1",
                        "bot_alias_id": "TSTALIASID"
                    }
                }
            }
        }
        
        # Simulate Docker environment variables
        docker_env = {
            "GATEWAY_HOST": "0.0.0.0",
            "GATEWAY_PORT": "50051",
            "MONITORING_HOST": "0.0.0.0",
            "MONITORING_PORT": "8080",
            "LOG_LEVEL": "INFO",
            "AWS_REGION": "us-east-1",
            "AWS_LEX_BOT_ALIAS_ID": "TSTALIASID",
            "AWS_LEX_BOT_NAME": "DockerBot",
            "AWS_LEX_LOCALE": "en_US"
        }
        
        # Set environment variables
        for key, value in docker_env.items():
            os.environ[key] = value
        
        try:
            result = override_config_with_env(config)
            
            # Verify all overrides
            assert result["gateway"]["host"] == "0.0.0.0"
            assert result["gateway"]["port"] == 50051
            assert result["monitoring"]["host"] == "0.0.0.0"
            assert result["monitoring"]["port"] == 8080
            assert result["logging"]["gateway"]["level"] == "INFO"
            assert result["connectors"]["aws_lex_connector"]["config"]["region_name"] == "us-east-1"
            assert result["connectors"]["aws_lex_connector"]["config"]["bot_alias_id"] == "TSTALIASID"
            assert result["connectors"]["aws_lex_connector"]["config"]["bot_name"] == "DockerBot"
            assert result["connectors"]["aws_lex_connector"]["config"]["locale"] == "en_US"
            
        finally:
            # Clean up
            for key in docker_env.keys():
                if key in os.environ:
                    del os.environ[key]

    def test_production_environment_simulation(self):
        """Test simulating a production environment with IAM roles."""
        config = {
            "gateway": {
                "host": "0.0.0.0",
                "port": 50051
            },
            "connectors": {
                "aws_lex_connector": {
                    "config": {
                        "region_name": "us-east-1",
                        "bot_alias_id": "TSTALIASID"
                    }
                }
            }
        }
        
        # Simulate production environment variables (no AWS credentials, using IAM roles)
        prod_env = {
            "AWS_REGION": "us-west-2",
            "AWS_LEX_BOT_ALIAS_ID": "PRODALIASID",
            "AWS_LEX_BOT_NAME": "ProductionBot",
            "AWS_LEX_LOCALE": "en_US",
            "LOG_LEVEL": "WARNING"
        }
        
        # Set environment variables
        for key, value in prod_env.items():
            os.environ[key] = value
        
        try:
            result = override_config_with_env(config)
            
            # Verify production overrides
            assert result["connectors"]["aws_lex_connector"]["config"]["region_name"] == "us-west-2"
            assert result["connectors"]["aws_lex_connector"]["config"]["bot_alias_id"] == "PRODALIASID"
            assert result["connectors"]["aws_lex_connector"]["config"]["bot_name"] == "ProductionBot"
            assert result["connectors"]["aws_lex_connector"]["config"]["locale"] == "en_US"
            assert result["logging"]["gateway"]["level"] == "WARNING"
            
        finally:
            # Clean up
            for key in prod_env.keys():
                if key in os.environ:
                    del os.environ[key]

    def test_development_environment_simulation(self):
        """Test simulating a development environment with local overrides."""
        config = {
            "gateway": {
                "host": "0.0.0.0",
                "port": 50051
            },
            "monitoring": {
                "host": "0.0.0.0",
                "port": 8080
            },
            "logging": {
                "gateway": {
                    "level": "INFO"
                }
            }
        }
        
        # Simulate development environment variables
        dev_env = {
            "GATEWAY_HOST": "127.0.0.1",
            "MONITORING_HOST": "127.0.0.1",
            "LOG_LEVEL": "DEBUG"
        }
        
        # Set environment variables
        for key, value in dev_env.items():
            os.environ[key] = value
        
        try:
            result = override_config_with_env(config)
            
            # Verify development overrides
            assert result["gateway"]["host"] == "127.0.0.1"
            assert result["monitoring"]["host"] == "127.0.0.1"
            assert result["logging"]["gateway"]["level"] == "DEBUG"
            
        finally:
            # Clean up
            for key in dev_env.keys():
                if key in os.environ:
                    del os.environ[key]


# Fixture to clean up environment variables after each test
@pytest.fixture(autouse=True)
def cleanup_environment():
    """Clean up environment variables after each test."""
    # Store original environment
    original_env = os.environ.copy()
    
    yield
    
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)
