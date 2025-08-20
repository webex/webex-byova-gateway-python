#!/usr/bin/env python3
"""
Test runner script for the Webex BYOVA Gateway Python project.

This script sets up the Python path and runs the test suite using pytest.
It can be run directly or used as a module.
"""

import sys
import os
import subprocess
from pathlib import Path

def setup_python_path():
    """Add the src directory to the Python path for imports."""
    project_root = Path(__file__).parent
    src_path = project_root / "src"
    
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
        print(f"Added {src_path} to Python path")

def run_tests():
    """Run the test suite using pytest."""
    setup_python_path()
    
    # Get the project root directory
    project_root = Path(__file__).parent
    
    # Change to the project root directory
    os.chdir(project_root)
    
    # Check if pytest is available
    try:
        import pytest
        print(f"Using pytest version: {pytest.__version__}")
    except ImportError:
        print("Error: pytest is not installed. Please install it with:")
        print("pip install pytest pytest-asyncio")
        return 1
    
    # Run the tests
    print("Running test suite...")
    print(f"Project root: {project_root}")
    print(f"Test directory: {project_root / 'tests'}")
    print("-" * 50)
    
    try:
        # Run pytest with common options
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            "tests/",
            "-v",
            "--tb=short",
            "--color=yes"
        ], capture_output=False, text=True)
        
        return result.returncode
        
    except subprocess.CalledProcessError as e:
        print(f"Error running tests: {e}")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1

def run_specific_test(test_path):
    """Run a specific test file or test function."""
    setup_python_path()
    
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    try:
        import pytest
    except ImportError:
        print("Error: pytest is not installed.")
        return 1
    
    print(f"Running specific test: {test_path}")
    print("-" * 50)
    
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            test_path,
            "-v",
            "--tb=short",
            "--color=yes"
        ], capture_output=False, text=True)
        
        return result.returncode
        
    except subprocess.CalledProcessError as e:
        print(f"Error running test: {e}")
        return 1

def main():
    """Main entry point for the test runner."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run the test suite")
    parser.add_argument(
        "test_path", 
        nargs="?", 
        help="Specific test file or test function to run"
    )
    parser.add_argument(
        "--list", 
        action="store_true", 
        help="List available tests without running them"
    )
    
    args = parser.parse_args()
    
    if args.list:
        # List available tests
        setup_python_path()
        project_root = Path(__file__).parent
        os.chdir(project_root)
        
        try:
            subprocess.run([
                sys.executable, "-m", "pytest",
                "tests/",
                "--collect-only",
                "-q"
            ], capture_output=False, text=True)
        except subprocess.CalledProcessError:
            print("Error listing tests")
            return 1
        return 0
    
    if args.test_path:
        # Run specific test
        return run_specific_test(args.test_path)
    else:
        # Run all tests
        return run_tests()

if __name__ == "__main__":
    sys.exit(main())
