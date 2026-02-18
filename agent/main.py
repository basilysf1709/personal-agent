import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent.claude_agent import run_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Personal Agent")


class IncomingAttachment(BaseModel):
    base64: str
    filename: str
    mimetype: str


class WebhookRequest(BaseModel):
    sender: str
    text: str
    attachment: IncomingAttachment | None = None


class FileAttachment(BaseModel):
    base64: str
    filename: str
    mimetype: str


class WebhookResponse(BaseModel):
    reply: str
    file: FileAttachment | None = None


@app.post("/webhook", response_model=WebhookResponse)
async def webhook(req: WebhookRequest):
    log.info(f"Message from {req.sender}: {req.text}")
    if req.attachment:
        log.info(f"Attachment: {req.attachment.filename} ({req.attachment.mimetype})")

    try:
        # Build message with attachment context if present
        user_message = req.text
        attachment_data = None
        if req.attachment:
            attachment_data = {
                "base64": req.attachment.base64,
                "filename": req.attachment.filename,
                "mimetype": req.attachment.mimetype,
            }

        result = run_agent(user_message, attachment=attachment_data)
        reply = result["text"]
        file_data = result.get("file")
        log.info(f"Reply to {req.sender}: {reply[:100]}...")
        if file_data:
            log.info(f"Outgoing file: {file_data['filename']}")
        return WebhookResponse(
            reply=reply,
            file=FileAttachment(**file_data) if file_data else None,
        )
    except Exception as e:
        log.error(f"Agent error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}
