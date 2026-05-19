import os
from groq import Groq
from dotenv import dotenv_values

# ─── Environment Setup ────────────────────────────────────────────────────────
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(UTILS_DIR)
env_config = dotenv_values(os.path.join(PROJECT_DIR, ".env"))

GROQ_API_KEY = env_config.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")

# Initialize Groq client
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

def ask_ai(message, context_stats):
    """Query Groq API (llama-3.1-8b-instant) with context about the user's storage and recent activity."""
    if not groq_client:
        return "Error: GROQ_API_KEY is not configured in the backend."

    recent_activity_str = ""
    if context_stats.get('recent_activity'):
        recent_activity_str = "Recent User Activity:\n"
        for act in context_stats['recent_activity']:
            recent_activity_str += f"- {act['action'].capitalize()} '{act['file_name']}' (v{act['version'] or 1}) on {act['timestamp']}\n"

    system_prompt = (
        "You are CloudShield AI, a smart contextual Cloud Backup AI Assistant. "
        "Keep all replies accurate, contextual, and short — under 3 sentences when possible. "
        f"User storage stats: {context_stats['total_files']} file(s), "
        f"{context_stats['total_versions']} version(s), "
        f"{context_stats['total_folders']} folder(s), "
        f"{context_stats['total_storage']} used.\n"
        f"{recent_activity_str}\n"
        "Use this real database data to answer questions about recent uploads, deletes, downloads, or restores. "
        "If asked about recent activity, list the specific filenames and actions. "
        "Be helpful, factual, and professional."
    )

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": message}
            ],
            temperature=0.2,
            max_tokens=150
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Sorry, I encountered an error communicating with my AI brain: {str(e)}"
