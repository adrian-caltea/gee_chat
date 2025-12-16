# Backend (FastAPI + RAG + Streaming)

## Setup (Python 3.10+ recommended)
1. cd backend
2. python -m venv .venv
3. source .venv/bin/activate
4. pip install -r requirements.txt
5. put training text into data/training.txt
6. export GEMINI_API_KEY="your_key"
7. uvicorn app:app --reload --port 8000
