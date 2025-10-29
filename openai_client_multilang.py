# openai_client_multilang.py - Multi-language OpenAI client
import os
from dotenv import load_dotenv
from openai import OpenAI
from typing import Optional

# Load environment variables first
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Configure models
TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
SUMMARIZE_MODEL = os.getenv("OPENAI_SUMMARIZE_MODEL", "gpt-4o-mini")

def transcribe_file_multilang(file_path: str, language: Optional[str] = None) -> str:
    """Transcribe audio file with language support"""
    try:
        from openai_client import transcribe_file
        return transcribe_file(file_path, language)
    except Exception as e:
        print(f"Warning: transcribe_file_multilang failed: {e}")
        raise

def summarize_text_multilang(text: str, language_code: str = "hi", instructions: str = "", max_tokens: int = 800, temperature: float = 0.1) -> str:
    """Return a structured summary with language support"""
    try:
        from language_handler_v2 import get_summary_instructions, get_language_name
        lang_instruction = get_summary_instructions(language_code)
        lang_name = get_language_name(language_code)
    except Exception as e:
        print(f"Warning: Failed to get language instructions: {e}")
        lang_instruction = "Please provide the meeting summary."
        lang_name = "Hindi"
    
    prompt = f"""You are a professional meeting summarizer. Create comprehensive meeting minutes.

IMPORTANT: You MUST respond in {lang_name} language only. Do not use any other language.

Language Instructions: {lang_instruction}
Additional Instructions: {instructions}

Meeting Content:
{text}

Provide a well-structured summary with:
- Key discussion points
- Important decisions made  
- Action items with owners (if mentioned)
- Next steps

Format as clear, readable text in {lang_name} language only.
"""
    
    try:
        system_message = f"You are an expert meeting summarizer who creates clear, actionable meeting minutes. You MUST respond ONLY in {lang_name} language. Never use Hindi if another language is requested. Always respect the requested language."
        
        response = client.chat.completions.create(
            model=SUMMARIZE_MODEL,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=temperature
        )
        summary = response.choices[0].message.content.strip()
        return summary[:1500] + "..." if len(summary) > 1500 else summary
    except Exception as e:
        print(f"Warning: Summarization failed: {e}")
        raise
