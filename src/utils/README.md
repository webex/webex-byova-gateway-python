# Audio Utilities

This package contains utility functions for audio format conversion, specifically designed to ensure compatibility with Webex Contact Center (WxCC).

## AudioConverter Class

The `AudioConverter` class provides comprehensive audio format conversion capabilities:

### Methods

#### `resample_16khz_to_8khz(pcm_16khz_data, bit_depth=16)`
Resamples 16kHz PCM audio to 8kHz using simple decimation.

**Args:**
- `pcm_16khz_data`: Raw PCM audio data at 16kHz
- `bit_depth`: Audio bit depth (default: 16)

**Returns:** Resampled PCM audio data at 8kHz

#### `pcm_to_ulaw(pcm_data, sample_rate=8000, bit_depth=16)`
Converts raw PCM audio data to u-law format for WxCC compatibility.

**Args:**
- `pcm_data`: Raw PCM audio data
- `sample_rate`: Source sample rate (default: 8000)
- `bit_depth`: Source bit depth (default: 16)

**Returns:** u-law encoded audio data as bytes

#### `pcm_to_wav(pcm_data, sample_rate=8000, bit_depth=8, channels=1, encoding="ulaw")`
Converts raw PCM audio data to WAV format compatible with WxCC.

**Args:**
- `pcm_data`: Raw PCM audio data
- `sample_rate`: Audio sample rate in Hz (default: 8000)
- `bit_depth`: Audio bit depth (default: 8)
- `channels`: Number of audio channels (default: 1)
- `encoding`: Audio encoding (default: "ulaw")

**Returns:** WAV format audio data as bytes

#### `convert_aws_lex_audio_to_wxcc(pcm_16khz_data, bit_depth=16, convert_to_wav=True)`
Complete conversion from AWS Lex audio format to WxCC-compatible format.

**Args:**
- `pcm_16khz_data`: Raw PCM audio data from AWS Lex (16kHz, 16-bit)
- `bit_depth`: Source bit depth (default: 16)
- `convert_to_wav`: Whether to convert to WAV format (default: True)

**Returns:** Tuple of (audio_data, content_type)

## Convenience Functions

For simple use cases, you can use the convenience functions directly:

- `resample_16khz_to_8khz(pcm_16khz_data, bit_depth=16, logger=None)`
- `pcm_to_ulaw(pcm_data, sample_rate=8000, bit_depth=16, logger=None)`
- `pcm_to_wav(pcm_data, sample_rate=8000, bit_depth=8, channels=1, encoding="ulaw", logger=None)`
- `convert_aws_lex_audio_to_wxcc(pcm_16khz_data, bit_depth=16, convert_to_wav=True, logger=None)`

## Usage Examples

### Basic Usage

```python
from src.utils.audio_utils import convert_aws_lex_audio_to_wxcc

# Convert AWS Lex audio to WxCC-compatible format
audio_data, content_type = convert_aws_lex_audio_to_wxcc(
    pcm_16khz_data, 
    bit_depth=16, 
    convert_to_wav=True
)
```

### Using the AudioConverter Class

```python
from src.utils.audio_utils import AudioConverter

converter = AudioConverter(logger=my_logger)

# Resample 16kHz to 8kHz
pcm_8khz = converter.resample_16khz_to_8khz(pcm_16khz_data)

# Convert to u-law
ulaw_audio = converter.pcm_to_ulaw(pcm_8khz, sample_rate=8000, bit_depth=16)

# Convert to WAV
wav_audio = converter.pcm_to_wav(ulaw_audio, sample_rate=8000, bit_depth=8, encoding="ulaw")
```

## WxCC Audio Requirements

The utilities ensure compatibility with WxCC's audio requirements:

- **Sample Rate**: 8000 Hz (8kHz) - REQUIRED to avoid 5-second delays
- **Bit Depth**: 8-bit - REQUIRED for proper audio playback
- **Encoding**: u-law - REQUIRED for WxCC compatibility
- **Channels**: 1 (mono) - REQUIRED for WxCC compatibility

## Error Handling

All methods include comprehensive error handling and will return the original audio data if conversion fails, ensuring the system remains robust even when audio conversion encounters issues.
