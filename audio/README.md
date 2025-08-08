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
│   ├── welcome.wav
│   ├── welcome-message.mp3
│   └── greeting.flac
├── responses/
│   ├── default_response.wav
│   ├── transferring.wav
│   └── help-response.ogg
├── goodbye/
│   ├── goodbye.wav
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
        welcome: "welcome.wav"
        transfer: "transferring.wav"
        goodbye: "goodbye.wav"
        error: "error.wav"
        default: "default_response.wav"
```

## Usage Examples

### Local Audio Connector

The `LocalAudioConnector` uses audio files to simulate virtual agent responses:

```python
# Audio file mapping in connector
audio_files = {
    "welcome": "welcome.wav",
    "transfer": "transferring.wav", 
    "goodbye": "goodbye.wav",
    "error": "error.wav",
    "default": "default_response.wav"
}

# Usage in connector
def start_conversation(self, conversation_id: str, request_data: dict) -> dict:
    audio_file = self.audio_files.get("welcome")
    audio_path = os.path.join(self.audio_base_path, audio_file)
    
    with open(audio_path, 'rb') as f:
        audio_content = f.read()
    
    return {
        "audio_content": audio_content,
        "text": "Welcome to our virtual agent"
    }
```