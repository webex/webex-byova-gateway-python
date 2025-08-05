# Audio Files

This directory contains audio files used by the local connector implementation for testing and development purposes.

## Purpose

Audio files serve multiple purposes in the BYOVA Gateway:

- **Testing**: Validate audio playback functionality
- **Development**: Provide sample audio for development workflows
- **Demo**: Demonstrate virtual agent capabilities
- **Unit Testing**: Automated testing of audio processing
- **Prototyping**: Rapid prototyping of voice interactions

## Supported Formats

The gateway supports the following audio formats:

- **WAV** (recommended for testing)
  - Uncompressed, high quality
  - Widely supported across platforms
  - Good for development and testing

- **MP3**
  - Compressed format, smaller file sizes
  - Good for production use
  - Compatible with most audio players

- **FLAC**
  - Lossless compression
  - High quality with smaller file sizes
  - Good for professional audio applications

- **OGG**
  - Open source format
  - Good compression ratios
  - Web-friendly format

## File Organization

### Recommended Structure

```
audio/
├── welcome/
│   ├── test-welcome.wav
│   ├── welcome-message.mp3
│   └── greeting.flac
├── responses/
│   ├── test-response.wav
│   ├── transfer-message.mp3
│   └── help-response.ogg
├── goodbye/
│   ├── test-goodbye.wav
│   ├── farewell.mp3
│   └── thank-you.flac
└── samples/
    ├── sample-1.wav
    ├── sample-2.mp3
    └── sample-3.ogg
```

### Naming Conventions

- **Descriptive Names**: Use clear, descriptive filenames
- **Consistent Format**: Stick to one format per use case
- **Version Control**: Include version numbers if needed
- **Language Indicators**: Add language codes for multi-language support

## Configuration

Audio files are configured in the main `config.yaml`:

```yaml
connectors:
  - name: "my_local_test_agent"
    type: "local_audio_connector"
    class: "LocalAudioConnector"
    module: "connectors.local_audio_connector"
    config:
      agent_id: "Local Playback"
      audio_base_path: "audio"
      audio_files:
        welcome: "test-welcome.wav"
        transfer: "test-response.wav"
        goodbye: "test-goodbye.wav"
        error: "error-message.wav"
        help: "help-message.wav"
```

## Usage Examples

### Local Audio Connector

The `LocalAudioConnector` uses audio files to simulate virtual agent responses:

```python
# Audio file mapping in connector
audio_files = {
    "welcome": "test-welcome.wav",
    "transfer": "test-response.wav", 
    "goodbye": "test-goodbye.wav"
}

# Usage in connector
def start_session(self, session_id: str, request_data: dict) -> dict:
    audio_file = self.audio_files.get("welcome")
    audio_path = os.path.join(self.audio_base_path, audio_file)
    
    with open(audio_path, 'rb') as f:
        audio_content = f.read()
    
    return {
        "audio_content": audio_content,
        "text": "Welcome to our virtual agent"
    }
```

### Testing Audio Files

```bash
# Test audio file playback
python -c "
import wave
with wave.open('audio/test-welcome.wav', 'rb') as wav:
    print(f'Channels: {wav.getnchannels()}')
    print(f'Sample width: {wav.getsampwidth()}')
    print(f'Frame rate: {wav.getframerate()}')
    print(f'Frames: {wav.getnframes()}')
    print(f'Duration: {wav.getnframes() / wav.getframerate():.2f}s')
"

# Check file size and format
ls -la audio/
file audio/*.wav
```

## Audio Quality Guidelines

### For Testing
- **Duration**: 5-30 seconds for test messages
- **Quality**: 16-bit, 44.1kHz for WAV files
- **Content**: Clear, professional speech
- **Format**: WAV for best compatibility

### For Production
- **Compression**: Use MP3 or FLAC for efficiency
- **Quality**: 128kbps+ for MP3, lossless for FLAC
- **Normalization**: Ensure consistent volume levels
- **Metadata**: Include proper audio metadata

## Best Practices

### File Management
- **Version Control**: Keep audio files in version control
- **Backup**: Maintain backups of important audio files
- **Organization**: Use subdirectories for different audio types
- **Documentation**: Document audio file purposes and usage

### Performance
- **File Sizes**: Keep files reasonably sized for quick loading
- **Caching**: Consider caching frequently used audio files
- **Compression**: Use appropriate compression for your use case
- **Streaming**: Implement streaming for large audio files

### Quality Assurance
- **Testing**: Test audio playback across different scenarios
- **Validation**: Verify audio files are properly formatted
- **Monitoring**: Monitor audio playback success rates
- **Feedback**: Collect feedback on audio quality and clarity

## Troubleshooting

### Common Issues

1. **File Not Found**: Check file paths and permissions
2. **Format Errors**: Verify audio file format compatibility
3. **Playback Issues**: Test audio files independently
4. **Size Problems**: Monitor file sizes and loading times

### Debug Commands

```bash
# Check audio file properties
ffprobe audio/test-welcome.wav

# Convert audio format
ffmpeg -i input.wav -acodec mp3 output.mp3

# Normalize audio levels
ffmpeg -i input.wav -af "loudnorm" output.wav

# Check file integrity
python -c "
import wave
try:
    with wave.open('audio/test-welcome.wav', 'rb') as wav:
        print('File is valid WAV')
except Exception as e:
    print(f'Error: {e}')
"
```

## Security Considerations

- **File Validation**: Validate audio files before processing
- **Path Security**: Use secure file path handling
- **Access Control**: Restrict access to audio file directory
- **Malware Scanning**: Scan uploaded audio files for malware

## License

This code is licensed under the [Cisco Sample Code License v1.1](../LICENSE). See the main project README for details.

**Note**: Audio files may be subject to their own licensing terms. Ensure you have proper rights to use any audio content. 