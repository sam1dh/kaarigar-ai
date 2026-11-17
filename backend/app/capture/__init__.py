"""Phase 2 — Capture: expert voice note -> structured, approved repair record.

Package layout
- adapters.py        the ONLY file that imports Phase 0/1 code (auth, db, storage, search, chunks)
- settings.py        Phase 2 settings (read from the same .env)
- audio.py           any browser recording -> 16 kHz mono WAV segments (bundled ffmpeg)
- sarvam.py          Sarvam Saaras speech-to-text (mode=translate -> English)
- llm.py             Groq structured outputs with strict->best-effort fallback
- translate.py       English <-> user language for the check screen
- repo.py            all SQL for this phase (tenant-scoped)
- graph.py           the LangGraph Capture graph (two human checks via interrupt())
- runner.py          checkpointer + start / resume / retry / discard
- router_capture.py  /capture/* (expert, phone)
- router_review.py   /manager/* review queue (supervisor, web)
"""
