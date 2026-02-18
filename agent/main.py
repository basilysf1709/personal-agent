import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent.claude_agent import run_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Personal Agent")


class WebhookRequest(BaseModel):
    sender: str
    text: str


class WebhookResponse(BaseModel):
    reply: str


@app.post("/webhook", response_model=WebhookResponse)
async def webhook(req: WebhookRequest):
    log.info(f"Message from {req.sender}: {req.text}")
    try:
        reply = run_agent(req.text)
        log.info(f"Reply to {req.sender}: {reply[:100]}...")
        return WebhookResponse(reply=reply)
    except Exception as e:
        log.error(f"Agent error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}
