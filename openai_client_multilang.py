# openai_client_multilang.py - Multi-language OpenAI client
import os
from openai import OpenAI
from typing import Optional

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Configure models
TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
SUMMARIZE_MODEL = os.getenv("OPENAI_SUMMARIZE_MODEL", "gpt-4o-mini")

def transcribe_file_multilang(file_path: str, language: Optional[str] = None) -> str:
    """Transcribe audio file with language support"""
    from openai_client import transcribe_file
    return transcribe_file(file_path, language)

def summarize_text_multilang(text: str, instructions: str = "", max_tokens: int = 800, temperature: float = 0.1, language_code: str = "hi") -> str:
    """Return a structured summary with language support"""
    from language_handler_v2 import get_summary_instructions
    lang_instruction = get_summary_instructions(language_code)
    
    prompt = f"""You are a professional meeting summarizer. Create comprehensive meeting minutes.

Language Instructions: {lang_instruction}
Additional Instructions: {instructions}

Meeting Content:
{text}

Provide a well-structured summary with:
- Key discussion points
- Important decisions made
- Action items with owners (if mentioned)
- Next steps

Format as clear, readable text (not JSON).
"""
    
    try:
        response = client.chat.completions.create(
            model=SUMMARIZE_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert meeting summarizer who creates clear, actionable meeting minutes."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=temperature
        )
        summary = response.choices[0].message.content.strip()
        return summary[:1500] + "..." if len(summary) > 1500 else summary
    except Exception as e:
        print(f"Summarization failed: {e}")
        raise