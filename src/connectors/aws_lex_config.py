"""
AWS Lex Configuration Manager for Webex Contact Center BYOVA Gateway.

This module handles all configuration-related operations for the AWS Lex connector,
including configuration validation, default values, and environment-specific settings.
"""

import logging
import os
from typing import Any, Dict, Optional


class AWSLexConfig:
    """
    Manages all configuration-related operations for AWS Lex connector.
    
    This class encapsulates configuration validation, default values, and
    environment-specific settings to keep the main connector focused on business logic.
    """

    # Default configuration values
    DEFAULT_BOT_ALIAS_ID = "TSTALIASID"
    DEFAULT_LOCALE_ID = "en_US"
    DEFAULT_TEXT_REQUEST_CONTENT_TYPE = "text/plain; charset=utf-8"
    DEFAULT_AUDIO_REQUEST_CONTENT_TYPE = "audio/l16; rate=16000; channels=1"
    DEFAULT_RESPONSE_CONTENT_TYPE = "audio/pcm"
    DEFAULT_BARGE_IN_ENABLED = False
    DEFAULT_INITIAL_TRIGGER_TEXT = "hello"
    
    # Required configuration keys
    REQUIRED_CONFIG_KEYS = ["region_name"]
    
    # Audio logging default configuration
    DEFAULT_AUDIO_LOGGING = {
        "enabled": True,
        "output_dir": "logs/audio_recordings",
        "filename_format": "{conversation_id}_{timestamp}_{source}.wav",
        "log_all_audio": True,
        "max_file_size": 10485760,  # 10MB
        "sample_rate": 8000,
        "bit_depth": 8,
        "channels": 1,
        "encoding": "ulaw"
    }

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize the configuration manager.

        Args:
            config: Configuration dictionary from the main config file
            logger: Logger instance (optional, will create one if not provided)
        """
        self.logger = logger or logging.getLogger(__name__)
        self._config = config
        self._validated_config = {}
        
        # Validate and process configuration
        self._validate_and_process_config()

    def _validate_and_process_config(self) -> None:
        """
        Validate and process the configuration.
        
        Raises:
            ValueError: If required configuration is missing or invalid
        """
        try:
            # Check required configuration keys
            for key in self.REQUIRED_CONFIG_KEYS:
                if key not in self._config:
                    raise ValueError(f"Required configuration key '{key}' is missing")
                if not self._config[key]:
                    raise ValueError(f"Required configuration key '{key}' cannot be empty")

            # Process region name
            self._validated_config["region_name"] = self._config["region_name"]
            
            # Process AWS credentials (optional)
            self._validated_config["aws_access_key_id"] = self._config.get("aws_access_key_id")
            self._validated_config["aws_secret_access_key"] = self._config.get("aws_secret_access_key")
            
            # Process bot alias ID
            self._validated_config["bot_alias_id"] = self._config.get("bot_alias_id", self.DEFAULT_BOT_ALIAS_ID)
            
            # Process locale ID
            self._validated_config["locale_id"] = self._config.get("locale_id", self.DEFAULT_LOCALE_ID)
            
            # Process content types
            self._validated_config["text_request_content_type"] = self._config.get("text_request_content_type", self.DEFAULT_TEXT_REQUEST_CONTENT_TYPE)
            self._validated_config["audio_request_content_type"] = self._config.get("audio_request_content_type", self.DEFAULT_AUDIO_REQUEST_CONTENT_TYPE)
            self._validated_config["response_content_type"] = self._config.get("response_content_type", self.DEFAULT_RESPONSE_CONTENT_TYPE)
            
            # Process barge-in configuration
            self._validated_config["barge_in_enabled"] = self._config.get("barge_in_enabled", self.DEFAULT_BARGE_IN_ENABLED)
            
            # Process initial trigger text for conversation start
            self._validated_config["initial_trigger_text"] = self._config.get("initial_trigger_text", self.DEFAULT_INITIAL_TRIGGER_TEXT)
            
            # Process audio logging configuration
            self._validated_config["audio_logging"] = self._process_audio_logging_config()
            
            # Process additional configuration options
            self._validated_config["max_retries"] = self._config.get("max_retries", 3)
            self._validated_config["timeout"] = self._config.get("timeout", 30)
            self._validated_config["enable_debug_logging"] = self._config.get("enable_debug_logging", False)
            
            self.logger.debug("Configuration validation completed successfully")
            
        except Exception as e:
            self.logger.error(f"Configuration validation failed: {e}")
            raise

    def _process_audio_logging_config(self) -> Dict[str, Any]:
        """
        Process audio logging configuration with defaults.
        
        Returns:
            Processed audio logging configuration
        """
        audio_logging_config = self._config.get("audio_logging", {})
        
        # Merge with defaults
        processed_config = self.DEFAULT_AUDIO_LOGGING.copy()
        processed_config.update(audio_logging_config)
        
        # Ensure output directory exists if audio logging is enabled
        if processed_config["enabled"]:
            output_dir = processed_config["output_dir"]
            if not os.path.exists(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    self.logger.debug(f"Created audio logging directory: {output_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to create audio logging directory {output_dir}: {e}")
                    # Disable audio logging if directory creation fails
                    processed_config["enabled"] = False
        
        return processed_config

    def get_region_name(self) -> str:
        """
        Get the AWS region name.
        
        Returns:
            AWS region name
        """
        return self._validated_config["region_name"]

    def get_aws_credentials(self) -> Dict[str, Optional[str]]:
        """
        Get AWS credentials configuration.
        
        Returns:
            Dictionary with aws_access_key_id and aws_secret_access_key
        """
        return {
            "aws_access_key_id": self._validated_config["aws_access_key_id"],
            "aws_secret_access_key": self._validated_config["aws_secret_access_key"]
        }

    def get_bot_alias_id(self) -> str:
        """
        Get the bot alias ID.
        
        Returns:
            Bot alias ID
        """
        return self._validated_config["bot_alias_id"]

    def get_locale_id(self) -> str:
        """
        Get the locale ID.
        
        Returns:
            Locale ID
        """
        return self._validated_config["locale_id"]

    def get_text_request_content_type(self) -> str:
        """
        Get the text request content type.
        
        Returns:
            Text request content type
        """
        return self._validated_config["text_request_content_type"]

    def get_audio_request_content_type(self) -> str:
        """
        Get the audio request content type.
        
        Returns:
            Audio request content type
        """
        return self._validated_config["audio_request_content_type"]

    def get_response_content_type(self) -> str:
        """
        Get the response content type.
        
        Returns:
            Response content type
        """
        return self._validated_config["response_content_type"]

    def is_barge_in_enabled(self) -> bool:
        """
        Check if barge-in is enabled for responses.
        
        Returns:
            True if barge-in is enabled, False otherwise
        """
        return self._validated_config["barge_in_enabled"]

    def get_initial_trigger_text(self) -> str:
        """
        Get the initial trigger text to send when starting a conversation.
        
        Returns:
            Initial trigger text (e.g., "hello")
        """
        return self._validated_config["initial_trigger_text"]

    def get_audio_logging_config(self) -> Dict[str, Any]:
        """
        Get the audio logging configuration.
        
        Returns:
            Audio logging configuration dictionary
        """
        return self._validated_config["audio_logging"]

    def is_audio_logging_enabled(self) -> bool:
        """
        Check if audio logging is enabled.
        
        Returns:
            True if audio logging is enabled, False otherwise
        """
        return self._validated_config["audio_logging"]["enabled"]

    def get_max_retries(self) -> int:
        """
        Get the maximum number of retries.
        
        Returns:
            Maximum retry count
        """
        return self._validated_config["max_retries"]

    def get_timeout(self) -> int:
        """
        Get the timeout value in seconds.
        
        Get the timeout value in seconds.
        
        Returns:
            Timeout value in seconds
        """
        return self._validated_config["timeout"]

    def is_debug_logging_enabled(self) -> bool:
        """
        Check if debug logging is enabled.
        
        Returns:
            True if debug logging is enabled, False otherwise
        """
        return self._validated_config["enable_debug_logging"]

    def get_all_config(self) -> Dict[str, Any]:
        """
        Get all validated configuration.
        
        Returns:
            Complete validated configuration dictionary
        """
        return self._validated_config.copy()

    def get_config_summary(self) -> str:
        """
        Get a summary of the configuration for logging.
        
        Returns:
            Configuration summary string
        """
        summary_parts = [
            f"region: {self.get_region_name()}",
            f"bot_alias: {self.get_bot_alias_id()}",
            f"locale: {self.get_locale_id()}",
            f"barge_in: {'enabled' if self.is_barge_in_enabled() else 'disabled'}",
            f"audio_logging: {'enabled' if self.is_audio_logging_enabled() else 'disabled'}",
            f"max_retries: {self.get_max_retries()}",
            f"timeout: {self.get_timeout()}s"
        ]
        
        if self.get_aws_credentials()["aws_access_key_id"]:
            summary_parts.append("credentials: explicit")
        else:
            summary_parts.append("credentials: default_chain")
            
        return ", ".join(summary_parts)

    def validate_aws_region(self, region_name: str) -> bool:
        """
        Validate if the AWS region name is in a valid format.
        
        Args:
            region_name: AWS region name to validate
            
        Returns:
            True if valid, False otherwise
        """
        # Basic validation - AWS regions follow the pattern: us-east-1, eu-west-1, etc.
        import re
        pattern = r'^[a-z]{2}-[a-z]+-\d+$'
        return bool(re.match(pattern, region_name))

    def get_environment_specific_config(self) -> Dict[str, Any]:
        """
        Get environment-specific configuration overrides.
        
        Returns:
            Environment-specific configuration dictionary
        """
        env_config = {}
        
        # Check for environment variables
        if os.getenv("AWS_LEX_REGION"):
            env_config["region_name"] = os.getenv("AWS_LEX_REGION")
            
        if os.getenv("AWS_LEX_BOT_ALIAS_ID"):
            env_config["bot_alias_id"] = os.getenv("AWS_LEX_BOT_ALIAS_ID")
            
        if os.getenv("AWS_LEX_LOCALE_ID"):
            env_config["locale_id"] = os.getenv("AWS_LEX_LOCALE_ID")
            
        if os.getenv("AWS_LEX_ENABLE_DEBUG"):
            env_config["enable_debug_logging"] = os.getenv("AWS_LEX_ENABLE_DEBUG").lower() == "true"
            
        if os.getenv("AWS_LEX_MAX_RETRIES"):
            try:
                env_config["max_retries"] = int(os.getenv("AWS_LEX_MAX_RETRIES"))
            except ValueError:
                self.logger.warning(f"Invalid AWS_LEX_MAX_RETRIES value: {os.getenv('AWS_LEX_MAX_RETRIES')}")
                
        if os.getenv("AWS_LEX_TIMEOUT"):
            try:
                env_config["timeout"] = int(os.getenv("AWS_LEX_TIMEOUT"))
            except ValueError:
                self.logger.warning(f"Invalid AWS_LEX_TIMEOUT value: {os.getenv('AWS_LEX_TIMEOUT')}")
        
        return env_config

    def update_config(self, updates: Dict[str, Any]) -> None:
        """
        Update configuration with new values.
        
        Args:
            updates: Dictionary of configuration updates
            
        Note: This will trigger re-validation of the configuration
        """
        self._config.update(updates)
        self._validate_and_process_config()
        self.logger.info("Configuration updated and re-validated")

    def reset_to_defaults(self) -> None:
        """Reset configuration to default values."""
        self._config = {}
        self._validate_and_process_config()
        self.logger.info("Configuration reset to defaults")
