"""
Generated protobuf code module.
This package contains auto-generated code from protobuf definitions.
DO NOT EDIT any files in this directory manually.
"""

import sys
import os

# Add the current directory to the Python path so generated files can find each other
current_dir = os.path.dirname(__file__)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Import the protobuf modules
from . import byova_common_pb2
from . import voicevirtualagent_pb2
from . import voicevirtualagent_pb2_grpc

# Make them available at the package level
__all__ = ['byova_common_pb2', 'voicevirtualagent_pb2', 'voicevirtualagent_pb2_grpc']

# Also make them available as if they were at root level for backward compatibility
sys.modules['byova_common_pb2'] = byova_common_pb2
sys.modules['voicevirtualagent_pb2'] = voicevirtualagent_pb2
sys.modules['voicevirtualagent_pb2_grpc'] = voicevirtualagent_pb2_grpc