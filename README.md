# 🎬 Batch Subtitle Translator (SRT) via Ollama API

This Python program batch-translates `.srt` subtitle files using the [Ollama API](http://127.0.0.1:11434/api/generate). It is designed to process directories containing movies, automatically detect and translate subtitle files to a specified target language, and clean up model output to maintain subtitle formatting.

---

## 🚀 Features

- ⚙️ Translates `.srt` subtitles using a configurable Ollama model and endpoint.
- 🧠 Smart prompt engineering and post-processing for cleaner output.
- 🔄 Skips or force-translates files based on existence and flags.
- 📁 Supports batch processing of folders and parallel translation.
- 🧹 Cleans Ollama output from meta-text, tags, and unintended commentary.
- ✅ Preserves original subtitle timestamps and structure.

---

## 🧩 Requirements

- Python 3.8+
- Install dependencies:

```bash
pip install -r requirements.txt
```

### `requirements.txt`

```txt
srt
requests
tqdm
```

---

## 📦 Usage

```bash
python translate_subtitles.py <movies_root_dir> <target_language_name> <target_language_code> [OPTIONS]
```

### Positional Arguments

| Argument               | Description                                                 |
|------------------------|-------------------------------------------------------------|
| `movies_root_dir`      | Root directory with subfolders for each movie               |
| `target_language_name` | Full language name (e.g., "Spanish")                        |
| `target_language_code` | ISO language code for file naming (e.g., `es`, `fr`, `de`)  |

### Optional Flags

| Flag                          | Description                                                                 |
|-------------------------------|-----------------------------------------------------------------------------|
| `--source_language_name`      | Name of the source language (default: `"English"`)                          |
| `--source_language_code`      | Code of the source language (default: `"en"`)                               |
| `--model`                     | Ollama model to use (default: `"qwen3:30b-a3b"`)                            |
| `--ollama_url`                | URL to the Ollama API (default: `"http://ai.mythx.nl/api/generate"`)       |
| `--force_translate`           | Force re-translation even if output file exists                             |
| `--skip_if_target_exists`     | Skip processing if target file exists (default: `True`)                     |
| `--no-skip_if_target_exists`  | Disable skipping if target file exists                                      |
| `--workers <n>`               | Number of threads to use (default: `3`)                                     |

---

## 🗂 Folder Structure Example

```
movies/
├── MovieA/
│   ├── sub_en.srt
│   └── sub_fr.srt (created)
├── MovieB/
│   ├── sub_en.srt
│   └── sub_es.srt (created)
```

---

## 🧠 Translation Strategy

- Translates only the text content of subtitle lines.
- Strips unintended output like:
  - Meta-comments (`Here is the translation:`)
  - Tags (`<think>`)
  - Extraneous punctuation/quotes
- Maintains original timing and format.
- Automatically avoids translating files that:
  - Are already in the target language.
  - Match the target filename (unless `--force_translate` is used).

---

## 🛠 Example

```bash
python batch_srt_translator.py "C:\Users\pc\Desktop\srt\movie" "nederlands" "nl" --workers 3
```

This will translate all `.srt` files in subfolders under `./movies/` from English to Spanish using the Ollama API.

---

## 💬 Output Example

```text
[Thread-140423155242688 | MOVIE: MovieA] --- Starting processing ---
  Found preferred source SRT (English): sub_en.srt
    Translating sub_en.srt (154 lines) to Spanish...
  [SUCCESS] Translated SRT saved to: MovieA/sub_es.srt
[Thread-140423155242688 | MOVIE: MovieA] --- Finished processing ---
```

---

## 🧾 License

MIT License. Feel free to modify and use.
