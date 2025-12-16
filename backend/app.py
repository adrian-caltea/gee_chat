import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from rag_index import RAGIndex
from llm_client import LLMClient

TRAINING_PATH = os.getenv("TRAINING_PATH", "./data/training.txt")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
# Allow running in a local development mode when no API key is present.
# Set USE_DEV_LLM=1 in the environment to force dev-mode LLM even if a key exists.
USE_DEV_LLM = os.getenv("USE_DEV_LLM", "").lower() in ("1", "true", "yes")
if not GEMINI_KEY and not USE_DEV_LLM:
    # Warn but don't crash; a lazy LLM factory will raise on use if needed.
    print("Warning: GEMINI_API_KEY not set — the application will run in dev mode if USE_DEV_LLM=1 is set or calls that require the real LLM will return an error.")

rag = None
llm = None

def get_rag():
    global rag
    if rag is None:
        try:
            rag = RAGIndex(txt_path=TRAINING_PATH)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize RAGIndex: {e}")
    return rag

def get_llm():
    global llm
    if llm is None:
        try:
            llm = LLMClient(api_key=GEMINI_KEY, model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite"))
        except Exception as e:
            raise RuntimeError(f"Failed to initialize LLMClient: {e}")
    return llm

app = FastAPI(title="Training Chat - FastAPI RAG Streaming")

# Enable CORS so the frontend (localhost:4200) can access the API and SSE endpoints
from fastapi.middleware.cors import CORSMiddleware

origins = [
    "http://localhost:4200",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type"],
)

class AskRequest(BaseModel):
    question: str

def build_prompt(chunks, question):
    context = "".join(chunks)
    prompt = f"""You are a helpful assistant trained on the provided training document context below.
Answer the question using ONLY the information in the DOCUMENT_CONTEXT. If the information is not present, respond exactly:
"The document does not contain this information."

DOCUMENT_CONTEXT:
{context}

QUESTION:
{question}

Provide a concise, accurate answer. If steps are requested, use bullets or numbered steps."""
    return prompt

@app.get("/")
async def health():
    return {"status":"ok"}

@app.post("/ask")
async def ask_one(req: AskRequest):
    question = req.question
    try:
        r = get_rag()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    top = r.query(question, top_k=6)
    if not top:
        return JSONResponse({"answer": "No context available from the document."})
    prompt = build_prompt(top, question)
    print(f"\n{'='*50}\n[/ask] Prompt sent to Gemini:\n{'='*50}\n{prompt}\n{'='*50}\n")
    try:
        l = get_llm()
        ans = l.generate(prompt, max_output_tokens=512)
        return JSONResponse({"answer": ans})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stream")
async def stream(request: Request, prompt: str):
    try:
        r = get_rag()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    top = r.query(prompt, top_k=6)
    prompt_with_context = build_prompt(top, prompt)
    print(f"\n{'='*50}\n[/stream] Prompt sent to Gemini:\n{'='*50}\n{prompt_with_context}\n{'='*50}\n")

    async def event_generator():
        try:
            l = get_llm()
        except Exception as e:
            yield {"data": f"[ERROR] {str(e)}"}
            return
        # Inform UI the model has started producing an answer (typing indicator)
        yield {"event": "typing", "data": ""}
        for chunk in l.stream_generate(prompt_with_context, max_output_tokens=512):
            if await request.is_disconnected():
                break
            yield {"data": chunk}
        yield {"event":"done", "data": "[DONE]"}

    return EventSourceResponse(event_generator())
