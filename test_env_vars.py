#!/usr/bin/env python3
"""
Quick test script to verify environment variable functionality in main.py
"""

import os
import sys
import tempfile
import yaml
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from main import override_config_with_env, load_config

def test_override_config_with_env():
    """Test the override_config_with_env function"""
    print("Testing override_config_with_env function...")
    
    # Test configuration
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
    
    # Set environment variables
    os.environ["GATEWAY_HOST"] = "127.0.0.1"
    os.environ["GATEWAY_PORT"] = "60051"
    os.environ["MONITORING_HOST"] = "127.0.0.1"
    os.environ["MONITORING_PORT"] = "9080"
    os.environ["LOG_LEVEL"] = "DEBUG"
    os.environ["AWS_REGION"] = "eu-west-1"
    os.environ["AWS_LEX_BOT_ALIAS_ID"] = "PRODALIASID"
    os.environ["AWS_LEX_BOT_NAME"] = "TestBot"
    os.environ["AWS_LEX_LOCALE"] = "en_GB"
    
    # Test override
    result = override_config_with_env(config)
    
    # Verify overrides
    assert result["gateway"]["host"] == "127.0.0.1", f"Expected 127.0.0.1, got {result['gateway']['host']}"
    assert result["gateway"]["port"] == 60051, f"Expected 60051, got {result['gateway']['port']}"
    assert result["monitoring"]["host"] == "127.0.0.1", f"Expected 127.0.0.1, got {result['monitoring']['host']}"
    assert result["monitoring"]["port"] == 9080, f"Expected 9080, got {result['monitoring']['port']}"
    assert result["logging"]["gateway"]["level"] == "DEBUG", f"Expected DEBUG, got {result['logging']['gateway']['level']}"
    assert result["connectors"]["aws_lex_connector"]["config"]["region_name"] == "eu-west-1", f"Expected eu-west-1, got {result['connectors']['aws_lex_connector']['config']['region_name']}"
    assert result["connectors"]["aws_lex_connector"]["config"]["bot_alias_id"] == "PRODALIASID", f"Expected PRODALIASID, got {result['connectors']['aws_lex_connector']['config']['bot_alias_id']}"
    assert result["connectors"]["aws_lex_connector"]["config"]["bot_name"] == "TestBot", f"Expected TestBot, got {result['connectors']['aws_lex_connector']['config']['bot_name']}"
    assert result["connectors"]["aws_lex_connector"]["config"]["locale"] == "en_GB", f"Expected en_GB, got {result['connectors']['aws_lex_connector']['config']['locale']}"
    
    print("✅ override_config_with_env function works correctly!")
    
    # Clean up environment variables
    env_vars_to_clean = [
        "GATEWAY_HOST", "GATEWAY_PORT", "MONITORING_HOST", "MONITORING_PORT",
        "LOG_LEVEL", "AWS_REGION", "AWS_LEX_BOT_ALIAS_ID", "AWS_LEX_BOT_NAME", "AWS_LEX_LOCALE"
    ]
    for var in env_vars_to_clean:
        if var in os.environ:
            del os.environ[var]

def test_load_config_with_env_vars():
    """Test the load_config function with environment variables"""
    print("Testing load_config function with environment variables...")
    
    # Create a temporary config file
    config_data = {
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
        assert result["gateway"]["host"] == "192.168.1.100", f"Expected 192.168.1.100, got {result['gateway']['host']}"
        assert result["connectors"]["aws_lex_connector"]["config"]["region_name"] == "ap-southeast-1", f"Expected ap-southeast-1, got {result['connectors']['aws_lex_connector']['config']['region_name']}"
        assert result["connectors"]["aws_lex_connector"]["config"]["bot_alias_id"] == "TESTALIASID", f"Expected TESTALIASID, got {result['connectors']['aws_lex_connector']['config']['bot_alias_id']}"
        
        print("✅ load_config function with environment variables works correctly!")
        
    finally:
        # Clean up
        os.unlink(temp_config_path)
        env_vars_to_clean = ["GATEWAY_HOST", "AWS_REGION", "AWS_LEX_BOT_ALIAS_ID"]
        for var in env_vars_to_clean:
            if var in os.environ:
                del os.environ[var]

def test_no_env_vars():
    """Test that config works without environment variables"""
    print("Testing configuration without environment variables...")
    
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
    
    # Test override with no environment variables
    result = override_config_with_env(config)
    
    # Should remain unchanged
    assert result["gateway"]["host"] == "0.0.0.0", f"Expected 0.0.0.0, got {result['gateway']['host']}"
    assert result["gateway"]["port"] == 50051, f"Expected 50051, got {result['gateway']['port']}"
    assert result["connectors"]["aws_lex_connector"]["config"]["region_name"] == "us-east-1", f"Expected us-east-1, got {result['connectors']['aws_lex_connector']['config']['region_name']}"
    assert result["connectors"]["aws_lex_connector"]["config"]["bot_alias_id"] == "TSTALIASID", f"Expected TSTALIASID, got {result['connectors']['aws_lex_connector']['config']['bot_alias_id']}"
    
    print("✅ Configuration without environment variables works correctly!")

if __name__ == "__main__":
    print("🧪 Testing Environment Variable Functionality")
    print("=" * 50)
    
    try:
        test_override_config_with_env()
        test_load_config_with_env_vars()
        test_no_env_vars()
        
        print("\n🎉 All environment variable tests passed!")
        print("✅ Environment variable functionality is working correctly!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
