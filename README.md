# MIDI to Image Converter

This project converts MIDI files to images in two ways:

1. **Local MIDI Visualization** (`midi_to_image.py`): Converts MIDI notes to colorful square images without external APIs
2. **AI Image Generation** (`stable_diffusion_client.py`): Uses Alibaba Cloud DashScope API to generate/refine images with Stable Diffusion

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
# Generate image from prompt
python stable_diffusion_client.py --prompt "a beautiful landscape"

# Generate with init image (image-to-image)
python stable_diffusion_client.py --prompt "a kid chasing the sun" --image output/recording_20251207_231145.png

# With workspace (for sub-accounts)
python stable_diffusion_client.py --prompt "test" --workspace your-workspace-id
```

## API Key Setup

The Stable Diffusion feature requires an Alibaba Cloud DashScope API key:

### Option 1: Get a Free API Key
1. Visit https://dashscope.aliyun.com/
2. Sign up for an account
3. Navigate to API Key management
4. Create a new API key with access to "Stable Diffusion" models

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
- `stable_diffusion_client.py` - AI image generation with DashScope API
- `files/` - Directory for recorded MIDI files
- `output/` - Directory for generated images

## Troubleshooting

### "Access denied" (403) Error
This means your API key is invalid, expired, or doesn't have permission:
1. Check your API key at https://dashscope.aliyuncs.com/console
2. Ensure you have sufficient quota/balance
3. Verify workspace ID if using `--workspace` parameter

### No API Key Available?
Use the local MIDI visualization instead:
```bash
python midi_to_image.py your_midi_file.mid
```

### Network Issues
- Check your internet connection
- Ensure you can access https://dashscope.aliyuncs.com
- Try without `--workspace` parameter first

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
