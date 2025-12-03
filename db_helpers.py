# db_helpers.py
import json
import traceback
from typing import Optional, Dict, Any
from db import get_conn  # adapt import if your db helper has a different name

def get_meeting_status(meeting_id: int) -> Optional[Dict[str, Any]]:
    """
    Lightweight: return meeting_id, status (PENDING|PROCESSING|DONE|FAILED), progress (0-100|null), error.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, job_state
                FROM meeting_notes
                WHERE id = %s
            """, (meeting_id,))
            row = cur.fetchone()
            if not row:
                return None
            _id, job_state = row
            return {
                "meeting_id": _id,
                "status": job_state or "pending",
                "progress": None,
                "error": None
            }
    except Exception as e:
        # If get_conn uses logging on exception, that's fine — bubble up as None for not found
        print("get_meeting_status error:", e, traceback.format_exc())
        return None

def get_meeting_detail(meeting_id: int) -> Optional[Dict[str, Any]]:
    """
    Return full meeting detail: status, transcript (decrypt before returning if needed),
    summary, audio_url, created_at, started_at, finished_at.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, job_state, audio_file, transcript, summary, created_at
                FROM meeting_notes
                WHERE id = %s
            """, (meeting_id,))
            row = cur.fetchone()
            if not row:
                return None
            _id, job_state, audio_file, transcript_enc, summary_enc, created_at = row

            try:
                from encryption import decrypt_sensitive_data
                transcript = decrypt_sensitive_data(transcript_enc) if transcript_enc else None
                summary = decrypt_sensitive_data(summary_enc) if summary_enc else None
            except Exception:
                transcript = transcript_enc
                summary = summary_enc

            return {
                "meeting_id": _id,
                "status": job_state or "pending",
                "audio_url": audio_file,
                "transcript": transcript,
                "summary": summary,
                "created_at": created_at.isoformat() if created_at else None,
                "started_at": None,
                "finished_at": None,
                "error": None
            }
    except Exception as e:
        print("get_meeting_detail error:", e, traceback.format_exc())
        return None
