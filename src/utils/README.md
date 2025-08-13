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
Converts raw PCM audio data to WAV format with proper headers.

**Args:**
- `pcm_data`: Raw PCM audio data
- `sample_rate`: Audio sample rate (default: 8000 for WxCC)
- `bit_depth`: Audio bit depth (default: 8 for WxCC)
- `channels`: Number of channels (default: 1 for mono)
- `encoding`: Audio encoding (default: "ulaw" for WxCC)

**Returns:** WAV format audio data as bytes

#### `convert_aws_lex_audio_to_wxcc(pcm_16khz_data, bit_depth=16)`
Complete conversion from AWS Lex audio format to WxCC-compatible format.

**Args:**
- `pcm_16khz_data`: Raw PCM audio data from AWS Lex (16kHz, 16-bit)
- `bit_depth`: Source bit depth (default: 16)

**Returns:** Tuple of (wav_audio_data, "audio/wav")

**Note:** WAV conversion is always enabled since WxCC requires complete WAV files with headers.

## Convenience Functions

The package also provides standalone convenience functions:

- `resample_16khz_to_8khz()` - Resample 16kHz PCM to 8kHz
- `pcm_to_ulaw()` - Convert PCM to u-law encoding
- `pcm_to_wav()` - Convert PCM to WAV format
- `convert_aws_lex_audio_to_wxcc()` - Complete AWS Lex to WxCC conversion

## WxCC Audio Requirements

The utilities ensure WxCC compatibility by providing:
- **Sample Rate**: 8kHz (avoids 5-second delays)
- **Bit Depth**: 8-bit (proper audio playback)
- **Encoding**: u-law (WxCC requirement)
- **Format**: WAV with proper headers (always required)

## Usage Example

```python
from src.utils.audio_utils import convert_aws_lex_audio_to_wxcc

# Convert AWS Lex audio to WxCC-compatible format
wav_audio, content_type = convert_aws_lex_audio_to_wxcc(
    pcm_audio_from_lex, 
    bit_depth=16
)

# wav_audio is now ready for WxCC (8kHz, 8-bit u-law WAV)
# content_type is always "audio/wav"
```

All methods include comprehensive error handling and will return the original audio data if conversion fails, ensuring the system remains robust even when audio conversion encounters issues.
