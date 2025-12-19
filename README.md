# MIDI to Image Converter

This project converts MIDI files to images in two ways:

1. **Local MIDI Visualization** (`midi_to_image.py`): Converts MIDI notes to colorful square images without external APIs
2. **AI Image Generation** (`run.py`): Uses Alibaba Cloud DashScope `qwen-image-plus` API to generate an image from the prompt

## New: Browser MIDI Studio (Web)

Record directly from a browser, see falling-note visuals, save MIDI, auto-generate the timing image and prompt, and call DashScope to “化乐为图”.

```bash
python web_app.py
# visit http://localhost:8000
```

What it does:
- Connect Web MIDI (Chrome/Edge recommended), play to hear a built-in synth with falling-note animation.
- One click to record; the server saves `files/<timestamp>.mid` and auto builds `output/<timestamp>.png` and `prompts/<timestamp>.txt`.
- Browser captures audio and offers an MP3 download.
- “化乐为图” calls DashScope `qwen-image-plus` (requires `DASHSCOPE_API_KEY` or `.dashscope_config.json`) and saves the image under `image/`.

## Quick Start

### 1. Local MIDI Visualization
```bash
# Convert a MIDI file to image
python midi_to_image.py files/recording_20251207_231145.mid

# With custom pixels per second
python midi_to_image.py files/recording_20251207_231145.mid --pps 100
```

### 2. AI Image Generation (Requires API Key)
```bash
# Generate image from an existing prompt txt file
python run.py prompts/recording_20251207_231145.txt

# Optional: choose size (default: 1664*928)
python run.py prompts/recording_20251207_231145.txt --size 1328*1328
```

## API Key Setup

The image generation feature requires an Alibaba Cloud DashScope API key:

### Option 1: Get a Free API Key
1. Visit https://dashscope.aliyun.com/
2. Sign up for an account
3. Navigate to API Key management
4. Create a new API key with access to image generation models (e.g. `qwen-image-plus`)

### Option 2: Configure the API Key

**Method A: Environment Variable (Recommended)**
```bash
# Windows (Command Prompt)
set DASHSCOPE_API_KEY=your-api-key-here

# Windows (PowerShell)
$env:DASHSCOPE_API_KEY="your-api-key-here"

# Linux/Mac
export DASHSCOPE_API_KEY="your-api-key-here"
```

**Method B: Configuration File**
Create `.dashscope_config.json` in the project root:
```json
{
  "api_key": "your-api-key-here"
}
```

## Project Structure

- `main.py` - MIDI recording and parsing utility
- `midi_parser.py` - MIDI file parsing utilities
- `midi_to_image.py` - Local MIDI visualization (no API needed)
- `run.py` - AI image generation with DashScope `qwen-image-plus` API
- `files/` - Directory for recorded MIDI files
- `output/` - Directory for generated images

## Troubleshooting

### "Access denied" (403) Error
This means your API key is invalid, expired, or doesn't have permission:
1. Check your API key at https://dashscope.aliyuncs.com/console
2. Ensure you have sufficient quota/balance
3. Ensure the API key has access to `qwen-image-plus` (image generation)

### No API Key Available?
Use the local MIDI visualization instead:
```bash
python midi_to_image.py your_midi_file.mid
```

### Network Issues
- Check your internet connection
- Ensure you can access https://dashscope.aliyuncs.com

## Dependencies

Install required packages:
```bash
pip install mido pillow requests
```

For Windows MIDI support, you may also need:
```bash
pip install python-rtmidi
```

## License

MIT License
