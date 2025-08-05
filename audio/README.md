# Audio Files

This directory contains placeholder audio files for the local connector implementation.

## Purpose

Audio files are used for:
- Testing the local connector
- Development and debugging
- Demo purposes
- Unit testing

## Supported Formats

- WAV (recommended for testing)
- MP3
- FLAC
- OGG

## Usage

Place audio files in this directory and reference them in your local connector configuration. The files should be:
- Named descriptively (e.g., `welcome_message.wav`)
- In a supported audio format
- Appropriate size for testing

## Example

```python
# In your local connector configuration
audio_file_path = "audio/welcome_message.wav"
``` 