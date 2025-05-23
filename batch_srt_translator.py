import srt
import requests
import json
import argparse
import os
import shutil # For more robust renaming/moving if needed
from tqdm import tqdm
import re # Added for regular expressions
from concurrent.futures import ThreadPoolExecutor, as_completed # Added for parallelism
import threading # For tqdm lock if needed, though often not strictly necessary for basic use

# --- Configuration (can be overridden by args) ---
OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate" # Your custom URL
DEFAULT_OLLAMA_MODEL = "qwen3:30b-a3b" # Your specified model
REQUEST_TIMEOUT = 180  # Increased timeout for potentially longer texts

# --- Helper Functions ---
def translate_text_ollama(text, source_language_name, target_language_name, model_name, ollama_url):
    """
    Translates a single piece of text using the Ollama API.
    """
    # Revised prompt for clarity and to guide the model better
    prompt = (
        f"You are an expert translator specializing in subtitle files.  /no_think Your task is to translate the given text from {source_language_name} to {target_language_name}.\n\n"
        f"**Instructions**:\n"
        f"1. Provide *only* the direct translation of the text.\n"
        f"2. Do *not* include any of your own commentary, thoughts, explanations, introductions, or conversational phrases (e.g., 'Here is the translation:', 'Okay, I will translate that for you:').\n"
        f"3. Do *not* include any meta-tags, XML-like tags, or markers such as '<think>', '</think>', or similar in your output.\n"
        f"4. Do *not* wrap the entire translated segment in quotation marks unless those quotation marks are an integral part of the actual dialogue being translated (e.g., a character quoting someone else).\n"
        f"5. Preserve the original meaning, nuance, and tone as faithfully as possible.\n"
        f"6. Maintain any existing line breaks within the subtitle text if they are important for formatting.\n"
        f"7. If the text contains proper names, specific technical terms, or unique cultural references that do not have direct equivalents or should remain in the original language, keep them as they are.\n\n"
        f"**Original {source_language_name} text to translate**:\n\"\"\"\n{text}\n\"\"\"\n\n"
        f"**Your {target_language_name} translation**:"
    )

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False
        # Optionally, you might try adding model-specific options if available, e.g.:
        # "options": {"temperature": 0.2, "repeat_penalty": 1.1}
    }
    try:
        response = requests.post(ollama_url, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        response_data = response.json()
        translated_text = response_data.get("response", "")

        # --- Start of Cleaning ---

        # 1. Remove <think>...</think> patterns (case-insensitive, multiline)
        #    This handles tags that might contain newlines or varying content.
        translated_text = re.sub(r"<think>.*?</think>", "", translated_text, flags=re.DOTALL | re.IGNORECASE)

        # 2. Remove standalone or potentially malformed <think> or </think> tags.
        #    These are case-sensitive simple replacements as a fallback or for specific known strings.
        translated_text = translated_text.replace("<think>", "")
        translated_text = translated_text.replace("</think>", "")
        translated_text = translated_text.replace("...", "")
        # You can add more specific tag cleaning here if other unwanted tags appear.

        # 3. Strip leading/trailing whitespace. Important before quote checking and for general cleanliness.
        translated_text = translated_text.strip()

        # 4. Strip leading/trailing quotes ONLY if they encapsulate the ENTIRE string.
        #    The prompt already instructs the model not to do this, but this is a fallback.
        if len(translated_text) >= 2: # Avoid errors on empty or single-character strings
            if translated_text.startswith('"') and translated_text.endswith('"'):
                translated_text = translated_text[1:-1]
            elif translated_text.startswith("'") and translated_text.endswith("'"):
                translated_text = translated_text[1:-1]
            # Consider adding other quote types if your model uses them (e.g., curly quotes “ ”)
            # elif translated_text.startswith('“') and translated_text.endswith('”'):
            #    translated_text = translated_text[1:-1]

        # 5. Remove common conversational prefixes that might have slipped through.
        #    This list can be expanded if other prefixes are observed.
        common_prefixes = [
            f"Your {target_language_name} translation:", # From our own prompt completion
            "Translated text:",
            "Translation:",
            "Here is the translation:",
            f"The {target_language_name} translation is:",
            f"The translation from {source_language_name} to {target_language_name} is:"
        ]
        # Ensure prefixes are checked case-insensitively
        temp_lower_text = translated_text.lower()
        for prefix in common_prefixes:
            if temp_lower_text.startswith(prefix.lower()):
                translated_text = translated_text[len(prefix):].lstrip() # lstrip to remove any space after prefix
                temp_lower_text = translated_text.lower() # Update for next iteration if multiple prefixes match
                # break # Usually, only one such prefix would occur. If multiple could stack, remove break.

        # 6. Final strip to clean up any whitespace potentially left by the above operations.
        translated_text = translated_text.strip()

        # --- End of Cleaning ---

        return translated_text
    except requests.exceptions.ConnectionError:
        # Adding thread ID for clarity when running in parallel
        print(f"\n[Thread-{threading.get_ident()}] [ERROR] Could not connect to Ollama API at {ollama_url}. Is Ollama running?")
    except requests.exceptions.Timeout:
        print(f"\n[Thread-{threading.get_ident()}] [ERROR] Request to Ollama API timed out for text: '{text[:50]}...'")
    except requests.exceptions.HTTPError as e:
        print(f"\n[Thread-{threading.get_ident()}] [ERROR] Ollama API request failed: {e.response.status_code} - {e.response.text}")
    except json.JSONDecodeError:
        print(f"\n[Thread-{threading.get_ident()}] [ERROR] Could not decode JSON response from Ollama API. Response: {response.text}")
    except Exception as e:
        print(f"\n[Thread-{threading.get_ident()}] [ERROR] An unexpected error occurred during translation: {e} (for text: '{text[:50]}...')")
    return None


def translate_srt_file_core(input_srt_path, output_srt_path, source_language_name, target_language_name, model_name, ollama_url):
    """
    Core SRT translation logic.
    """
    thread_id = threading.get_ident() # Get thread ID for logging
    movie_name_for_log = os.path.basename(os.path.dirname(input_srt_path)) # Get movie folder name

    try:
        with open(input_srt_path, 'r', encoding='utf-8') as f:
            srt_content = f.read()
    except Exception as e:
        print(f"[Thread-{thread_id} | {movie_name_for_log}] [ERROR] Could not read input SRT file {input_srt_path}: {e}")
        return False

    try:
        subtitles = list(srt.parse(srt_content))
    except Exception as e:
        print(f"[Thread-{thread_id} | {movie_name_for_log}] [ERROR] Could not parse SRT content from {input_srt_path}. Error: {e}")
        return False

    if not subtitles:
        print(f"[Thread-{thread_id} | {movie_name_for_log}] [INFO] SRT file {input_srt_path} is empty or unparsable.")
        return False

    translated_subtitles = []
    # Note: tqdm progress bars from multiple threads might interleave.
    # For cleaner output, you might disable the inner tqdm or use a thread lock for tqdm updates.
    # For simplicity, we'll leave it as is; it's often acceptable.
    # `position` can help if you know the worker ID, but that's more complex with ThreadPoolExecutor.
    print(f"  [Thread-{thread_id} | {movie_name_for_log}] Translating {os.path.basename(input_srt_path)} ({len(subtitles)} lines) to {target_language_name}...")

    for sub in tqdm(subtitles, desc=f"    Lines [{movie_name_for_log}]", unit="line", leave=False, position=0): # position=0 might help a bit
        original_text = sub.content
        if not original_text or not original_text.strip():
            translated_subtitles.append(srt.Subtitle(index=sub.index, start=sub.start, end=sub.end, content=original_text))
            continue

        translated_text = translate_text_ollama(original_text, source_language_name, target_language_name, model_name, ollama_url)

        if translated_text is not None:
            new_sub = srt.Subtitle(index=sub.index, start=sub.start, end=sub.end, content=translated_text)
            translated_subtitles.append(new_sub)
        else:
            print(f"\n  [Thread-{thread_id} | {movie_name_for_log}] [WARNING] Failed to translate line {sub.index} ('{original_text[:30]}...') from {os.path.basename(input_srt_path)} due to an error. Keeping original.")
            translated_subtitles.append(sub)

    if not translated_subtitles:
        print(f"[Thread-{thread_id} | {movie_name_for_log}] [ERROR] No subtitles were processed for {input_srt_path}.")
        return False

    try:
        final_srt_content = srt.compose(translated_subtitles)
        with open(output_srt_path, 'w', encoding='utf-8') as f:
            f.write(final_srt_content)
        print(f"  [Thread-{thread_id} | {movie_name_for_log}] [SUCCESS] Translated SRT saved to: {output_srt_path}")
        return True
    except Exception as e:
        print(f"[Thread-{thread_id} | {movie_name_for_log}] [ERROR] Could not write translated SRT file to {output_srt_path}: {e}")
        return False

def get_srt_files(folder_path):
    """Returns a list of .srt file paths in the given folder."""
    return [os.path.join(folder_path, f) for f in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, f)) and f.lower().endswith(".srt")]

def find_source_srt(srt_files, source_lang_code, source_lang_name_for_log, target_lang_code_to_avoid):
    """
    Finds a suitable source SRT file.
    Prioritizes files with source language code, then any other SRT not matching target.
    """
    preferred_sources = []
    other_sources = []
    thread_id = threading.get_ident() # For logging context

    for srt_path in srt_files:
        filename_lower = os.path.basename(srt_path).lower()
        if f".{target_lang_code_to_avoid}." in filename_lower or \
           f"-{target_lang_code_to_avoid}." in filename_lower or \
           f"sub_{target_lang_code_to_avoid}." in filename_lower or \
           f"sub.{target_lang_code_to_avoid}." in filename_lower:
            continue

        if f".{source_lang_code}." in filename_lower or f"-{source_lang_code}." in filename_lower or \
           f"sub_{source_lang_code}." in filename_lower or f"sub.{source_lang_code}." in filename_lower:
            preferred_sources.append(srt_path)
        else:
            other_sources.append(srt_path)

    if preferred_sources:
        print(f"    [Thread-{thread_id}] Found preferred source SRT ({source_lang_name_for_log}): {os.path.basename(preferred_sources[0])}")
        return preferred_sources[0]
    if other_sources:
        print(f"    [Thread-{thread_id}] Found other source SRT: {os.path.basename(other_sources[0])}")
        return other_sources[0]
    return None


def process_movie_folder(movie_path, target_language_name, target_language_code,
                         source_language_name, source_language_code,
                         model_name, ollama_url, force_translate, skip_if_target_exists):
    """
    Processes a single movie folder for SRT translation.
    This function will be run in a separate thread.
    """
    thread_id = threading.get_ident()
    movie_name = os.path.basename(movie_path)
    # Using a more prominent log format for the start of processing a movie folder in parallel
    print(f"\n[Thread-{thread_id} | MOVIE: {movie_name}] --- Starting processing ---")

    srt_files_in_folder = get_srt_files(movie_path)
    if not srt_files_in_folder:
        print(f"  [Thread-{thread_id} | {movie_name}] No SRT files found.")
        print(f"[Thread-{thread_id} | MOVIE: {movie_name}] --- Finished processing (no SRTs) ---")
        return

    expected_target_filename = f"sub_{target_language_code}.srt"
    expected_target_srt_path = os.path.join(movie_path, expected_target_filename)

    if os.path.exists(expected_target_srt_path):
        if force_translate:
            print(f"  [Thread-{thread_id} | {movie_name}] Target file {expected_target_filename} exists, but --force_translate is set. Re-translating.")
        elif skip_if_target_exists:
            print(f"  [Thread-{thread_id} | {movie_name}] Target file {expected_target_filename} already exists. Skipping.")
            print(f"[Thread-{thread_id} | MOVIE: {movie_name}] --- Finished processing (skipped) ---")
            return

    if not (os.path.exists(expected_target_srt_path) and skip_if_target_exists and not force_translate):
        for srt_f_path in srt_files_in_folder:
            if srt_f_path == expected_target_srt_path:
                continue
            srt_f_name_lower = os.path.basename(srt_f_path).lower()
            is_likely_target_lang = (
                f".{target_language_code}." in srt_f_name_lower or
                f"-{target_language_code}." in srt_f_name_lower or
                f".{target_language_name.lower()}." in srt_f_name_lower
            )
            if is_likely_target_lang:
                print(f"  [Thread-{thread_id} | {movie_name}] Found existing SRT likely in target language: {os.path.basename(srt_f_path)}")
                try:
                    if os.path.exists(expected_target_srt_path):
                        if force_translate:
                            print(f"    [Thread-{thread_id} | {movie_name}] Standard target {expected_target_filename} also exists. Will proceed to translate due to --force_translate.")
                        else:
                            print(f"    [Thread-{thread_id} | {movie_name}] Standard target {expected_target_filename} also exists. Not renaming {os.path.basename(srt_f_path)}.")
                    else:
                        print(f"    [Thread-{thread_id} | {movie_name}] Renaming {os.path.basename(srt_f_path)} to {expected_target_filename}.")
                        shutil.move(srt_f_path, expected_target_srt_path)
                        if not force_translate:
                            print(f"  [Thread-{thread_id} | {movie_name}] Renamed and target file {expected_target_filename} now exists. Skipping further translation.")
                            print(f"[Thread-{thread_id} | MOVIE: {movie_name}] --- Finished processing (renamed, not forced) ---")
                            return
                        else:
                            print(f"    [Thread-{thread_id} | {movie_name}] Renamed, but --force_translate is set. Will attempt to re-translate using a source file.")
                            srt_files_in_folder = get_srt_files(movie_path)
                except Exception as e:
                    print(f"  [Thread-{thread_id} | {movie_name}] [ERROR] Could not rename {os.path.basename(srt_f_path)} to {expected_target_filename}: {e}")
                break

    if os.path.exists(expected_target_srt_path) and not force_translate:
        print(f"  [Thread-{thread_id} | {movie_name}] Target file {expected_target_filename} is present, and --force_translate is not set. Skipping translation step.")
        print(f"[Thread-{thread_id} | MOVIE: {movie_name}] --- Finished processing (target present, not forced) ---")
        return

    srt_files_in_folder = get_srt_files(movie_path)
    source_srt_path = find_source_srt(srt_files_in_folder, source_language_code, source_language_name, target_language_code)

    if source_srt_path:
        if source_srt_path == expected_target_srt_path and not force_translate:
            print(f"  [Thread-{thread_id} | {movie_name}] Source SRT ({os.path.basename(source_srt_path)}) is the same as the target path, and --force_translate is not set. Skipping translation to avoid translating a file onto itself.")
            print(f"[Thread-{thread_id} | MOVIE: {movie_name}] --- Finished processing (source is target, not forced) ---")
            return

        print(f"  [Thread-{thread_id} | {movie_name}] Attempting translation from '{os.path.basename(source_srt_path)}' to '{expected_target_filename}'.")
        translate_srt_file_core(
            source_srt_path,
            expected_target_srt_path,
            source_language_name,
            target_language_name,
            model_name,
            ollama_url
        )
    else:
        print(f"  [Thread-{thread_id} | {movie_name}] No suitable source SRT file found for translation (to {target_language_name}, from {source_language_name}).")
    print(f"[Thread-{thread_id} | MOVIE: {movie_name}] --- Finished processing ---")


def main():
    parser = argparse.ArgumentParser(description="Batch translate .srt files in movie_name subfolders using Ollama.")
    parser.add_argument("movies_root_dir", help="Root directory containing movie_name subfolders (e.g., 'movies/').")
    parser.add_argument("target_language_name", help="Full target language name for translation prompt (e.g., 'French', 'Spanish').")
    parser.add_argument("target_language_code", help="Short target language code for filenames (e.g., 'fr', 'es' for sub_fr.srt).")

    parser.add_argument("--source_language_name", default="English", help="Full source language name (default: English).")
    parser.add_argument("--source_language_code", default="en", help="Short source language code for identifying source files (default: en).")

    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL, help=f"Ollama model (default: {DEFAULT_OLLAMA_MODEL}).")
    parser.add_argument("--ollama_url", default=OLLAMA_API_URL, help=f"Ollama API URL (default: {OLLAMA_API_URL}).")
    parser.add_argument("--force_translate", action="store_true", help="Force translation even if target SRT file already exists.")
    parser.add_argument("--skip_if_target_exists", action=argparse.BooleanOptionalAction, default=True,
                        help="Skip processing if target 'sub_<lang_code>.srt' exists (default: True). Use --no-skip_if_target_exists to disable.")
    parser.add_argument("--workers", type=int, default=3, help="Number of movie folders to process in parallel (default: 3).")


    args = parser.parse_args()

    print(f"--- Batch SRT Translator using Ollama ---")
    print(f"Movies Root: {args.movies_root_dir}")
    print(f"Target Language: {args.target_language_name} (code: {args.target_language_code})")
    print(f"Source Language: {args.source_language_name} (code: {args.source_language_code})")
    print(f"Ollama Model: {args.model}")
    print(f"Ollama URL: {args.ollama_url}")
    print(f"Force Translate: {args.force_translate}")
    print(f"Skip if Target Exists: {args.skip_if_target_exists}")
    print(f"Parallel Workers: {args.workers}")
    print("-----------------------------------------")

    if not os.path.isdir(args.movies_root_dir):
        print(f"[ERROR] Movies root directory not found: {args.movies_root_dir}")
        return

    movies_root_dir_abs = os.path.abspath(args.movies_root_dir)
    movie_folders_to_process = []

    for item_name in os.listdir(movies_root_dir_abs):
        item_path = os.path.join(movies_root_dir_abs, item_name)
        if os.path.isdir(item_path):
            movie_folders_to_process.append(item_path)

    if not movie_folders_to_process:
        print(f"[INFO] No movie subfolders found in {movies_root_dir_abs}.")
        return

    print(f"Found {len(movie_folders_to_process)} movie folders. Will process up to {args.workers} in parallel.")

    # Optional: If tqdm progress bars from threads become too messy,
    # you can create a lock and pass it to tqdm instances.
    # tqdm_lock = threading.RLock()
    # For tqdm, use: `with tqdm_lock: tqdm.write(...)` or pass `lock_args=(tqdm_lock,)`
    # However, multiple independent tqdm bars for lines might still interleave.
    # A single overall progress bar for movies is cleaner.

    processed_count = 0
    # Use ThreadPoolExecutor to process movie folders in parallel
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks to the executor
        future_to_movie_path = {
            executor.submit(
                process_movie_folder, # Function to execute
                movie_path,           # Arguments for the function
                args.target_language_name,
                args.target_language_code,
                args.source_language_name,
                args.source_language_code,
                args.model,
                args.ollama_url,
                args.force_translate,
                args.skip_if_target_exists
            ): movie_path for movie_path in movie_folders_to_process
        }

        # Use tqdm for overall progress as tasks complete
        # The inner tqdm instances for lines per movie will still exist and might interleave their output.
        for future in tqdm(as_completed(future_to_movie_path), total=len(movie_folders_to_process), desc="Overall Movie Progress", unit="movie"):
            movie_path_completed = future_to_movie_path[future]
            try:
                future.result()  # Retrieve result or raise exception from the completed task
                # process_movie_folder handles its own success/failure logging for translation
                # We're just ensuring the thread itself completed.
            except Exception as exc:
                # This catches exceptions that were not handled within process_movie_folder
                # or if process_movie_folder itself had a critical failure.
                print(f"\n[MAIN ERROR] Movie '{os.path.basename(movie_path_completed)}' processing generated an unexpected exception: {exc}")
                # You might want to log these to a file or handle them more robustly.
            processed_count += 1 # Count that a task (movie folder) has finished processing

    print(f"\n--- Finished processing {processed_count} movie folder(s) out of {len(movie_folders_to_process)} found. ---")


if __name__ == "__main__":
    main()