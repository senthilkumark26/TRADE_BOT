# AirLLM Integration Guide

This guide explains how to integrate and use AirLLM in your trading bot project.

## What is AirLLM?

AirLLM is a library that allows you to run large language models (7B+ parameters) on consumer hardware with limited VRAM. It uses layer-wise model splitting and quantization to run models that would normally require much more memory.

## Installation

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

This will install:
- `airllm>=2.11.0` - The AirLLM library
- `torch>=2.0.0` - PyTorch for model execution
- `transformers>=4.30.0` - HuggingFace transformers

## Configuration

### 1. Update config.json

Add or modify the `airllm` section in your `config.json`:

```json
{
  "llm_provider": "airllm",
  "airllm": {
    "enabled": true,
    "model_path": "garage-bAInd/Platypus2-70B-instruct",
    "compression": "4bit",
    "max_length": 128,
    "timeout": 120,
    "temperature": 0.2,
    "llm_timeout": 30.0,
    "trading_mode": "moderate",
    "fast_mode": true,
    "layer_shards_saving_path": null,
    "hf_token": null
  }
}
```

### Configuration Options

- **enabled**: Set to `true` to use AirLLM
- **model_path**: HuggingFace model ID or local path to model
- **compression**: `4bit`, `8bit`, or `null` (no compression)
- **max_length**: Maximum sequence length for generation
- **timeout**: Request timeout in seconds
- **temperature**: Sampling temperature (0.0 - 1.0)
- **llm_timeout**: LLM-specific timeout for engine2
- **trading_mode**: `conservative`, `moderate`, or `aggressive`
- **fast_mode**: Enable fast mode for quicker responses
- **layer_shards_saving_path**: Custom path to save split model layers
- **hf_token**: HuggingFace token for gated models

## Recommended Models

### For Testing (Smaller, Faster)
- `TinyLlama/TinyLlama-1.1B-Chat-v1.0` - 1.1B parameters (good for testing)
- `microsoft/phi-2` - 2.7B parameters (good performance)

### For Production (Larger, Smarter)
- `garage-bAInd/Platypus2-70B-instruct` - 70B parameters (default)
- `meta-llama/Llama-2-7b-hf` - 7B parameters (requires HF token)
- `meta-llama/Llama-2-13b-hf` - 13B parameters (requires HF token)

## Usage

### Switching to AirLLM

To switch from Ollama to AirLLM:

1. Change `llm_provider` in `config.json`:
```json
"llm_provider": "airllm"
```

2. Set `airllm.enabled` to `true`

3. Optionally disable other providers:
```json
"ollama": {
  "enabled": false
}
```

### Running the Bot

The bot will automatically use AirLLM when configured:

```bash
python trading_bot.py
```

or

```bash
python single_strike_trader.py
```

### Testing the Integration

Run the test script to verify AirLLM is working:

```bash
python test_airllm.py
```

## Performance Considerations

### Memory Usage

- **4bit compression**: ~4GB VRAM for 70B models
- **8bit compression**: ~8GB VRAM for 70B models
- **No compression**: ~16GB+ VRAM for 70B models

### Disk Space

AirLLM splits models layer-wise and saves them to disk. Ensure you have:
- At least 2x the model size in free disk space
- Default location: HuggingFace cache directory

### First Run

On the first run, AirLLM will:
1. Download the model (if using HuggingFace)
2. Split the model into layers
3. Save the split layers to disk

This can take 10-30 minutes depending on your internet speed and model size.

### Subsequent Runs

After the first run, loading is much faster as it uses the cached split layers.

## Troubleshooting

### Import Error

If you get `ImportError: No module named 'airllm'`:
```bash
pip install airllm
```

### CUDA Out of Memory

If you run out of VRAM:
1. Enable compression: `"compression": "4bit"`
2. Use a smaller model
3. Close other GPU-intensive applications

### Slow First Run

The first run is slow because:
- Model download (if needed)
- Model splitting and layer saving

Subsequent runs will be much faster.

### Model Download Issues

If model download fails:
1. Check your internet connection
2. For gated models, provide `hf_token` in config
3. Try downloading manually with HuggingFace CLI

## Comparison with Ollama

| Feature | AirLLM | Ollama |
|---------|--------|--------|
| VRAM Usage | Very low (4GB for 70B) | Higher |
| Model Size | Up to 70B+ | Typically < 30B |
| Setup | One-time split | Simple install |
| First Run | Slow (splitting) | Fast |
| Subsequent Runs | Fast | Fast |
| Quantization | Built-in | Manual |

## Example: Switching Between Providers

### Using Ollama
```json
{
  "llm_provider": "ollama",
  "ollama": {
    "enabled": true,
    "default_model": "qwen2:7b"
  },
  "airllm": {
    "enabled": false
  }
}
```

### Using AirLLM
```json
{
  "llm_provider": "airllm",
  "ollama": {
    "enabled": false
  },
  "airllm": {
    "enabled": true,
    "model_path": "garage-bAInd/Platypus2-70B-instruct",
    "compression": "4bit"
  }
}
```

## Advanced Usage

### Using Local Models

If you have downloaded models locally:

```json
{
  "airllm": {
    "model_path": "/path/to/local/model",
    "enabled": true
  }
}
```

### Custom Layer Save Path

To save split layers to a specific location:

```json
{
  "airllm": {
    "layer_shards_saving_path": "D:/Models/split_layers",
    "enabled": true
  }
}
```

### Gated Models

For models like Llama-2 that require access:

```json
{
  "airllm": {
    "model_path": "meta-llama/Llama-2-7b-hf",
    "hf_token": "your_huggingface_token_here",
    "enabled": true
  }
}
```

Get your token from: https://huggingface.co/settings/tokens

## Support

For issues with:
- **AirLLM library**: https://github.com/lyogavin/airllm
- **This integration**: Check the project issues or documentation