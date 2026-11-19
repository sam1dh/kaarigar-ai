"""Phase 3 — Assist: a technician asks by voice (or text) and gets a short, cited, spoken answer.

Package layout
- adapters.py          the ONLY file that imports Phase 0/1/2 code (user, db, storage, search, capture runner)
- settings.py          Phase 3 settings (same .env)
- errors.py            AssistError + user messages
- answer_format.py     source refs (E1/M1/H1), the answer line format, the parser, the NO_ANSWER gate
- prompts.py           prompts (answer, question -> English, answer -> English)
- llm.py               Groq streaming with model fallback + plain-text calls
- tts.py               Sarvam Bulbul text-to-speech (read aloud)
- repo.py              all SQL for this phase (tenant-scoped)
- pipeline.py          one question: transcribe -> understand -> search -> write (stream) -> save
- streaming.py         runs the pipeline in a worker thread and turns its events into Server-Sent Events
- views.py             DB rows -> API responses
- service.py           app wiring: init_assist / shutdown_assist / get_service, rate limits
- router_assist.py     /assist/*        (technician, phone)
- router_escalations.py /expert/* (expert inbox, phone) and /manager/escalations* (W2, web)
"""
