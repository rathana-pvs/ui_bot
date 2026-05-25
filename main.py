import asyncio
import os
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bot.mt5_interface import MT5Interface
from bot.engine import BotEngine

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MainServer")

app = FastAPI(title="Exness Volatility Adaptive Trading Bot")

# Global instances
mt5 = MT5Interface()  # Reads DRY_RUN setting from .env file or environment variables
bot = BotEngine(mt5)

# Ensure folders exist
os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


class ToggleRequest(BaseModel):
    active: bool

class RiskRequest(BaseModel):
    profile: str


@app.on_event("startup")
async def startup_event():
    # 1. Initialize MT5 Connection
    mt5.initialize()
    # 2. Start Bot loop in the background
    asyncio.create_task(bot.start_loop())
    logger.info("Application startup completed. Bot engine running in background.")

@app.on_event("shutdown")
async def shutdown_event():
    mt5.shutdown()
    logger.info("Application shutdown completed.")


# --- Dashboard HTML Page ---

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open("templates/index.html", "r") as f:
        return HTMLResponse(content=f.read())


# --- REST API Endpoints ---

@app.get("/api/status")
async def get_status():
    account = mt5.get_account_info()
    positions = mt5.get_open_positions()
    return {
        "bot": bot.stats,
        "account": account,
        "positions": positions
    }

@app.post("/api/toggle-bot")
async def toggle_bot(req: ToggleRequest):
    bot.set_active(req.active)
    return {"status": "success", "active": bot.is_active}

@app.post("/api/set-risk")
async def set_risk(req: RiskRequest):
    if req.profile not in ["safe", "moderate", "risk"]:
        raise HTTPException(status_code=400, detail="Invalid risk profile")
    bot.set_risk_profile(req.profile)
    return {"status": "success", "profile": bot.risk_profile}

@app.post("/api/close-all")
async def close_all_trades():
    success = mt5.close_all_positions()
    if success:
        bot.log_message("All active trades closed successfully.")
        return {"status": "success"}
    else:
        bot.log_message("Failed to close some or all active trades.")
        raise HTTPException(status_code=500, detail="Failed to close positions")

@app.post("/api/close-trade/{ticket}")
async def close_trade(ticket: int):
    success = mt5.close_position(ticket)
    if success:
        bot.log_message(f"Manually closed trade ticket: {ticket}")
        return {"status": "success"}
    else:
        bot.log_message(f"Failed to manually close trade ticket: {ticket}")
        raise HTTPException(status_code=404, detail="Trade not found or failed to close")


# --- WebSocket for Real-Time Dashboard Updates ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection established.")
    try:
        while True:
            # Stream status updates every 1.5 seconds
            account = mt5.get_account_info()
            positions = mt5.get_open_positions()
            
            data = {
                "bot": bot.stats,
                "account": account,
                "positions": positions
            }
            await websocket.send_json(data)
            await asyncio.sleep(1.5)
    except WebSocketDisconnect:
        logger.info("WebSocket connection disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
