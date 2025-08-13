"""
AWS Lex Connector for Webex Contact Center BYOVA Gateway.

This connector integrates with AWS Lex v2 to provide virtual agent capabilities.
It handles basic agent discovery and conversation initialization.
"""

import logging
from typing import Dict, Any, List
from botocore.exceptions import ClientError
import boto3
import struct

from .i_vendor_connector import IVendorConnector


class AWSLexConnector(IVendorConnector):
    """
    AWS Lex v2 connector for virtual agent integration.
    
    This connector provides a simple interface to AWS Lex bots using the
    standard TSTALIASID alias that most Lex bots have by default.
    
    Audio Format Configuration:
    - audio_sample_rate: Sample rate for WAV conversion (default: 8000 Hz for WxCC compatibility)
    - audio_bit_depth: Bit depth for WAV conversion (default: 8-bit for WxCC compatibility)
    - audio_channels: Number of channels for WAV conversion (default: 1 for mono)
    - convert_to_wav: Whether to convert PCM audio to WAV format (default: True)
    
    WxCC Audio Requirements:
    - Sample Rate: 8000 Hz (8kHz) - REQUIRED to avoid 5-second delays
    - Bit Depth: 8-bit - REQUIRED for proper audio playback
    - Encoding: u-law - REQUIRED for WxCC compatibility
    - Channels: 1 (mono) - REQUIRED for WxCC compatibility
    
    Audio Conversion Workflow:
    1. AWS Lex returns: 16kHz, 16-bit PCM audio
    2. Resample to: 8kHz, 16-bit PCM (simple decimation)
    3. Convert to: 8kHz, 8-bit u-law (WxCC compatible)
    4. Package as: 8kHz, 8-bit u-law WAV file
    
    Note: This connector automatically handles the complete audio format conversion
    from AWS Lex's 16kHz PCM to WxCC's required 8kHz u-law format.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the AWS Lex connector.
        
        Args:
            config: Configuration dictionary containing:
                - region_name: AWS region (required)
                - aws_access_key_id: AWS access key (optional, uses default chain)
                - aws_secret_access_key: AWS secret key (optional, uses default chain)
                - audio_sample_rate: Sample rate for WAV conversion (default: 8000 Hz for WxCC compatibility)
                - audio_bit_depth: Bit depth for WAV conversion (default: 8-bit for WxCC compatibility)
                - audio_channels: Number of channels for WAV conversion (default: 1 for mono)
                - convert_to_wav: Whether to convert PCM to WAV (default: True)
                
        Note: WxCC requires 8kHz, 8-bit u-law, mono audio to avoid 5-second delays.
        AWS Lex returns 16kHz, 16-bit PCM, which this connector automatically converts
        using proper resampling and encoding conversion.
        """
        # Extract configuration
        self.region_name = config.get('region_name')
        if not self.region_name:
            raise ValueError("region_name is required in AWS Lex connector configuration")
            
        # Optional explicit AWS credentials
        self.aws_access_key_id = config.get('aws_access_key_id')
        self.aws_secret_access_key = config.get('aws_secret_access_key')
        
        # Audio format configuration for WAV conversion
        self.audio_sample_rate = config.get('audio_sample_rate', 8000)  # Default: 8kHz (WxCC requirement)
        self.audio_bit_depth = config.get('audio_bit_depth', 8)        # Default: 8-bit (WxCC requirement)
        self.audio_channels = config.get('audio_channels', 1)          # Default: mono (WxCC requirement)
        self.convert_to_wav = config.get('convert_to_wav', True)      # Default: convert to WAV
        
        # Set up logging
        self.logger = logging.getLogger(__name__)
        
        # Initialize AWS clients
        self._init_aws_clients()
        
        # Cache for available bots
        self._available_bots = None
        
        # Mapping from display names to actual bot IDs
        self._bot_name_to_id_map = {}
        
        # Simple session storage for conversations
        self._sessions = {}
        
        self.logger.info(f"AWSLexConnector initialized for region: {self.region_name}")

    def _pcm_to_wav(self, pcm_data: bytes, sample_rate: int = 8000, bit_depth: int = 8, channels: int = 1, encoding: str = "ulaw") -> bytes:
        """
        Convert raw PCM audio data to WAV format compatible with WxCC.
        
        WxCC expects: 8kHz, 8-bit u-law, mono audio
        Avoid: 16kHz, 16-bit PCM (causes 5-second delay and missed caller responses)
        
        Args:
            pcm_data: Raw PCM audio data from AWS Lex
            sample_rate: Audio sample rate in Hz (default: 8000 for WxCC compatibility)
            bit_depth: Audio bit depth (default: 8 for WxCC compatibility)
            channels: Number of audio channels (default: 1 for mono)
            encoding: Audio encoding (default: "ulaw" for WxCC compatibility)
            
        Returns:
            WAV format audio data as bytes
        """
        try:
            # WAV file header constants
            RIFF_HEADER = b'RIFF'
            WAVE_FORMAT = b'WAVE'
            FMT_CHUNK = b'fmt '
            DATA_CHUNK = b'data'
            
            # WxCC-compatible audio format settings
            if encoding == "ulaw":
                # u-law encoding (WxCC preferred)
                audio_format = 7  # WAVE_FORMAT_MULAW
                bytes_per_sample = 1  # 8-bit u-law = 1 byte per sample
            else:
                # PCM encoding (fallback)
                audio_format = 1  # WAVE_FORMAT_PCM
                bytes_per_sample = bit_depth // 8
            
            # Calculate sizes
            block_align = channels * bytes_per_sample
            byte_rate = sample_rate * block_align
            data_size = len(pcm_data)
            file_size = 36 + data_size  # 36 bytes for headers + data size
            
            # Build WAV header with WxCC-compatible format
            wav_header = struct.pack('<4sI4s4sIHHIIHH4sI',
                RIFF_HEADER,           # RIFF identifier
                file_size,             # File size - 8
                WAVE_FORMAT,           # WAVE format
                FMT_CHUNK,             # Format chunk identifier
                16,                    # Format chunk size
                audio_format,          # Audio format (7 = u-law, 1 = PCM)
                channels,              # Number of channels (1 = mono)
                sample_rate,           # Sample rate (8000 Hz for WxCC)
                byte_rate,             # Byte rate
                block_align,           # Block align
                bit_depth,             # Bits per sample (8 for u-law)
                DATA_CHUNK,            # Data chunk identifier
                data_size              # Data size
            )
            
            # Combine header and audio data
            wav_data = wav_header + pcm_data
            
            self.logger.info(f"Converted PCM to WAV: {len(pcm_data)} bytes PCM -> {len(wav_data)} bytes WAV")
            self.logger.info(f"WAV format: {sample_rate}Hz, {bit_depth}bit, {channels} channel(s), encoding: {encoding}")
            self.logger.info(f"WxCC compatibility: {'YES' if sample_rate == 8000 and bit_depth == 8 and encoding == 'ulaw' else 'NO'}")
            
            return wav_data
            
        except Exception as e:
            self.logger.error(f"Error converting PCM to WAV: {e}")
            # Return original PCM data if conversion fails
            return pcm_data

    def _pcm_to_ulaw(self, pcm_data: bytes, sample_rate: int = 8000, bit_depth: int = 16) -> bytes:
        """
        Convert raw PCM audio data to u-law format for WxCC compatibility.
        
        WxCC expects 8-bit u-law encoding, but AWS Lex returns 16-bit PCM.
        This method converts the PCM data to u-law format.
        
        Args:
            pcm_data: Raw PCM audio data (typically 16-bit from Lex)
            sample_rate: Source sample rate (default: 8000)
            bit_depth: Source bit depth (default: 16)
            
        Returns:
            u-law encoded audio data as bytes
        """
        try:
            # Convert bytes to 16-bit integers (little-endian)
            if bit_depth == 16:
                # Convert 16-bit PCM to u-law
                pcm_samples = struct.unpack(f'<{len(pcm_data)//2}h', pcm_data)
            elif bit_depth == 8:
                # Convert 8-bit PCM to u-law
                pcm_samples = struct.unpack(f'<{len(pcm_data)}B', pcm_data)
                # Convert 8-bit unsigned to 16-bit signed
                pcm_samples = [(sample - 128) * 256 for sample in pcm_samples]
            else:
                self.logger.warning(f"Unsupported bit depth: {bit_depth}, returning original data")
                return pcm_data
            
            # Convert to u-law
            ulaw_samples = []
            for sample in pcm_samples:
                # Clamp sample to 16-bit range
                sample = max(-32768, min(32767, int(sample)))
                
                # Convert to u-law
                ulaw_byte = self._linear_to_ulaw(sample)
                ulaw_samples.append(ulaw_byte)
            
            ulaw_data = bytes(ulaw_samples)
            self.logger.info(f"Converted {len(pcm_data)} bytes PCM ({bit_depth}bit) to {len(ulaw_data)} bytes u-law")
            
            return ulaw_data
            
        except Exception as e:
            self.logger.error(f"Error converting PCM to u-law: {e}")
            # Return original PCM data if conversion fails
            return pcm_data

    def _resample_16khz_to_8khz(self, pcm_16khz_data: bytes, bit_depth: int = 16) -> bytes:
        """
        Resample 16kHz PCM audio to 8kHz using simple decimation.
        
        AWS Lex returns 16kHz, 16-bit PCM, but WxCC expects 8kHz.
        This method downsamples by taking every other sample (simple decimation).
        
        Args:
            pcm_16khz_data: Raw PCM audio data at 16kHz
            bit_depth: Audio bit depth (default: 16)
            
        Returns:
            Resampled PCM audio data at 8kHz
        """
        try:
            if bit_depth == 16:
                # Convert bytes to 16-bit integers (little-endian)
                samples_16khz = struct.unpack(f'<{len(pcm_16khz_data)//2}h', pcm_16khz_data)
                
                # Simple decimation: take every other sample to go from 16kHz to 8kHz
                samples_8khz = samples_16khz[::2]
                
                # Convert back to bytes
                pcm_8khz_data = struct.pack(f'<{len(samples_8khz)}h', *samples_8khz)
                
                self.logger.info(f"Resampled 16kHz to 8kHz: {len(pcm_16khz_data)} bytes -> {len(pcm_8khz_data)} bytes")
                self.logger.info(f"Sample count: {len(samples_16khz)} -> {len(samples_8khz)}")
                
                return pcm_8khz_data
                
            elif bit_depth == 8:
                # For 8-bit audio, take every other byte
                samples_8khz = pcm_16khz_data[::2]
                self.logger.info(f"Resampled 16kHz to 8kHz: {len(pcm_16khz_data)} bytes -> {len(samples_8khz)} bytes")
                return samples_8khz
                
            else:
                self.logger.warning(f"Unsupported bit depth for resampling: {bit_depth}, returning original data")
                return pcm_16khz_data
                
        except Exception as e:
            self.logger.error(f"Error resampling 16kHz to 8kHz: {e}")
            # Return original data if resampling fails
            return pcm_16khz_data

    def _linear_to_ulaw(self, sample: int) -> int:
        """
        Convert a 16-bit linear PCM sample to 8-bit u-law.
        
        Args:
            sample: 16-bit signed PCM sample (-32768 to 32767)
            
        Returns:
            8-bit u-law sample (0 to 255)
        """
        # u-law encoding table (simplified implementation)
        MULAW_BIAS = 0x84
        MULAW_CLIP = 32635
        
        # Clamp the sample
        if sample > MULAW_CLIP:
            sample = MULAW_CLIP
        elif sample < -MULAW_CLIP:
            sample = -MULAW_CLIP
        
        # Add bias
        sample += MULAW_BIAS
        
        # Get sign bit
        sign = (sample >> 8) & 0x80
        if sign != 0:
            sample = -sample
        if sample > MULAW_CLIP:
            sample = MULAW_CLIP
        
        # Find exponent
        exponent = 7
        mask = 0x4000
        while (sample & mask) == 0 and exponent > 0:
            mask >>= 1
            exponent -= 1
        
        # Calculate mantissa
        mantissa = (sample >> (exponent + 3)) & 0x0F
        
        # Combine into u-law byte
        ulaw_byte = ~(sign | (exponent << 4) | mantissa)
        
        return ulaw_byte & 0xFF

    def _init_aws_clients(self) -> None:
        """Initialize AWS Lex clients."""
        try:
            if self.aws_access_key_id and self.aws_secret_access_key:
                # Use explicit credentials
                session = boto3.Session(
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                    region_name=self.region_name
                )
                self.logger.info("Using explicit AWS credentials")
            else:
                # Use default credential chain
                session = boto3.Session(region_name=self.region_name)
                self.logger.info("Using default AWS credential chain")
            
            # Initialize clients
            self.lex_client = session.client('lexv2-models')  # For bot management
            self.lex_runtime = session.client('lexv2-runtime')  # For conversations
            
            self.logger.info("AWS Lex clients initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize AWS clients: {e}")
            raise

    def get_available_agents(self) -> List[str]:
        """
        Get available virtual agent IDs from AWS Lex.

        Returns:
            List of Lex bot IDs that can be used as virtual agents
        """
        if self._available_bots is None:
            try:
                self.logger.info("Fetching available Lex bots...")

                # List all bots in the region
                response = self.lex_client.list_bots()
                bots = response.get('botSummaries', [])

                # Extract bot IDs and names, format as "aws_lex_connector: Bot Name"
                bot_identifiers = []
                for bot in bots:
                    bot_id = bot['botId']
                    bot_name = bot.get('botName', bot_id)  # Use bot name if available, fallback to ID
                    display_name = f"aws_lex_connector: {bot_name}"
                    
                    # Store the mapping: display_name -> actual_bot_id
                    self._bot_name_to_id_map[display_name] = bot_id
                    
                    bot_identifiers.append(display_name)

                self._available_bots = bot_identifiers
                self.logger.info(f"Found {len(bot_identifiers)} available Lex bots: {bot_identifiers}")
                self.logger.info(f"Bot mappings: {self._bot_name_to_id_map}")

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                self.logger.error(f"AWS Lex API error ({error_code}): {error_message}")
                self._available_bots = []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching Lex bots: {e}")
                self._available_bots = []

        return self._available_bots

    def start_conversation(self, conversation_id: str, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start a new conversation with a Lex bot.
        
        Args:
            conversation_id: Unique conversation identifier
            request_data: Request data containing virtual_agent_id
            
        Returns:
            Response data for the new conversation with audio from Lex
        """
        try:
            # Get the display name from WxCC (e.g., "aws_lex_connector: Booking")
            display_name = request_data.get("virtual_agent_id", "")
            
            # Look up the actual bot ID from our mapping
            actual_bot_id = self._bot_name_to_id_map.get(display_name)
            if not actual_bot_id:
                raise ValueError(f"Bot not found in mapping: {display_name}. Available bots: {list(self._bot_name_to_id_map.keys())}")
            
            # Extract the friendly bot name for display
            bot_name = display_name.split(": ", 1)[1] if ": " in display_name else display_name

            # Create a simple session ID for Lex
            session_id = f"session_{conversation_id}"

            # Store session info with both names
            self._sessions[conversation_id] = {
                "session_id": session_id,
                "display_name": display_name,      # "aws_lex_connector: Booking"
                "actual_bot_id": actual_bot_id,    # "E7LNGX7D2J"
                "bot_name": bot_name               # "Booking"
            }

            self.logger.info(f"Started Lex conversation: {conversation_id} with bot: {bot_name} (ID: {actual_bot_id})")

            # Send initial text to Lex and get audio response
            try:
                # Convert text to bytes for the request
                text_input = "I need to book a hotel room"
                text_bytes = text_input.encode('utf-8')
                
                self.logger.info(f"Sending initial text to Lex: '{text_input}'")
                
                response = self.lex_runtime.recognize_utterance(
                    botId=actual_bot_id,
                    botAliasId='TSTALIASID',
                    localeId='en_US',
                    sessionId=session_id,
                    requestContentType='text/plain; charset=utf-8',
                    responseContentType='audio/pcm',
                    inputStream=text_bytes
                )
                
                self.logger.info(f"Lex API response received: {type(response)}")
                self.logger.info(f"Lex API response keys: {list(response.keys()) if hasattr(response, 'keys') else 'No keys'}")
                
                # Extract audio response
                audio_stream = response.get('audioStream')
                if audio_stream:
                    self.logger.info(f"Audio stream found: {type(audio_stream)}")
                    audio_response = audio_stream.read()
                    audio_stream.close()
                    self.logger.info(f"Received audio response from Lex (size: {len(audio_response)} bytes)")
                    
                    if audio_response:
                        self.logger.info(f"Audio content is valid, returning response with audio")
                        
                        # AWS Lex returns 16kHz, 16-bit PCM, but WxCC expects 8kHz, 8-bit u-law
                        # Step 1: Resample from 16kHz to 8kHz
                        pcm_8khz = self._resample_16khz_to_8khz(
                            audio_response, 
                            bit_depth=16  # Lex returns 16-bit PCM
                        )
                        
                        # Step 2: Convert 8kHz PCM to u-law format for WxCC compatibility
                        ulaw_audio = self._pcm_to_ulaw(
                            pcm_8khz, 
                            sample_rate=8000,  # Now at 8kHz
                            bit_depth=16       # Still 16-bit until u-law conversion
                        )
                        
                        # Step 3: Convert u-law audio to WAV format with WxCC-compatible settings
                        if self.convert_to_wav:
                            wav_audio = self._pcm_to_wav(
                                ulaw_audio, 
                                sample_rate=8000,      # WxCC expects 8kHz
                                bit_depth=8,           # WxCC expects 8-bit
                                channels=1,            # WxCC expects mono
                                encoding="ulaw"        # WxCC expects u-law
                            )
                            content_type = "audio/wav"
                            self.logger.info("Converted 16kHz PCM to WxCC-compatible WAV format (8kHz, 8-bit u-law)")
                        else:
                            wav_audio = ulaw_audio
                            content_type = "audio/ulaw"
                            self.logger.info("Keeping audio in u-law format for WxCC compatibility")
                        
                        return {
                            "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                            "audio_content": wav_audio,
                            "conversation_id": conversation_id,
                            "message_type": "welcome",
                            "barge_in_enabled": True,
                            "content_type": content_type
                        }
                    else:
                        self.logger.warning("Audio stream was empty, falling back to text-only response")
                        return {
                            "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                            "audio_content": b"",
                            "conversation_id": conversation_id,
                            "message_type": "welcome",
                            "barge_in_enabled": False
                        }
                else:
                    self.logger.error("No audio stream in Lex response")
                    # Check if there are other fields in the response
                    if hasattr(response, 'messages'):
                        self.logger.info(f"Lex messages: {response.messages}")
                    if hasattr(response, 'intentName'):
                        self.logger.info(f"Lex intent: {response.intentName}")
                    
                    return {
                        "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                        "audio_content": b"",
                        "conversation_id": conversation_id,
                        "message_type": "welcome",
                        "barge_in_enabled": False
                    }
                    
            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                self.logger.error(f"Lex API error during conversation start: {error_code} - {error_message}")
                
                # Fallback to text response
                return {
                    "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                    "audio_content": b"",
                    "conversation_id": conversation_id,
                    "message_type": "welcome",
                    "barge_in_enabled": True
                }
                
            except Exception as e:
                self.logger.error(f"Error getting audio response from Lex: {e}")
                self.logger.error(f"Exception type: {type(e)}")
                import traceback
                self.logger.error(f"Traceback: {traceback.format_exc()}")
                
                # Fallback to text response
                return {
                    "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                    "audio_content": b"",
                    "conversation_id": conversation_id,
                    "message_type": "welcome",
                    "barge_in_enabled": True
                }

        except Exception as e:
            self.logger.error(f"Error starting Lex conversation: {e}")
            self.logger.error(f"Exception type: {type(e)}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "text": "I'm having trouble starting our conversation. Please try again.",
                "audio_content": b"",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": False
            }

    def send_message(self, conversation_id: str, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Placeholder method for sending messages - functionality removed for debugging.
        
        Args:
            conversation_id: Active conversation identifier
            message_data: Message data containing input (audio or text)
            
        Returns:
            Placeholder response indicating functionality is disabled
        """
        return {
            "text": "Message handling functionality has been temporarily disabled for debugging.",
            "conversation_id": conversation_id,
            "message_type": "silence",
            "barge_in_enabled": False
        }

    def end_conversation(self, conversation_id: str, message_data: Dict[str, Any] = None) -> None:
        """
        End an active conversation and clean up resources.
        
        Args:
            conversation_id: Active conversation identifier
            message_data: Optional final message data
        """
        if conversation_id in self._sessions:
            bot_name = self._sessions[conversation_id].get("bot_name", "unknown")
            del self._sessions[conversation_id]
            self.logger.info(f"Ended Lex conversation: {conversation_id} with bot: {bot_name}")

    def convert_wxcc_to_vendor(self, wxcc_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert Webex Contact Center data format to vendor format.
        
        Args:
            wxcc_data: Data in WxCC format
            
        Returns:
            Data converted to vendor format
        """
        # For now, just return the data as-is
        # This can be enhanced later for specific format conversions
        return wxcc_data

    def convert_vendor_to_wxcc(self, vendor_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert vendor data format to Webex Contact Center format.
        
        Args:
            vendor_data: Data in vendor format
            
        Returns:
            Data converted to WxCC format
        """
        # For now, just return the data as-is
        # This can be enhanced later for specific format conversions
        return vendor_data

    def _refresh_bot_cache(self) -> None:
        """Refresh the cached list of available bots."""
        self._available_bots = None
        self._bot_name_to_id_map = {}  # Clear the mapping cache too
        self.get_available_agents()
