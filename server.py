import asyncio
import json
import os
import signal
from pathlib import Path
 
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse
from starlette.routing import Route
from contextlib import asynccontextmanager
 
# ── Config setup ────────────────────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".nanobot"
CONFIG_FILE = CONFIG_DIR / "config.json"
 
def write_config():
    """Write config.json from environment variables at startup."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
 
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    allow_from_raw = os.environ.get("TELEGRAM_ALLOW_FROM", "")
    allow_from = [x.strip() for x in allow_from_raw.split(",") if x.strip()]

    imap_host = os.environ.get("IMAP_HOST", "")
    imap_port = int(os.environ.get("IMAP_PORT", "993"))
    imap_user = os.environ.get("IMAP_USER", "")
    imap_password = os.environ.get("IMAP_PASSWORD", "")

    config = {
        "providers": {
            "anthropic": {
                "apiKey": anthropic_key
            }
        },
        "agents": {
            "defaults": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6"
            }
        },
      "channels": {
            "telegram": {
                "enabled": True,
                "token": telegram_token,
                "allowFrom": allow_from
            },
            "email": {
                "enabled": True,
                "imap": {
                    "host": imap_host,
                    "port": imap_port,
                    "username": imap_user,
                    "password": imap_password,
                    "tls": True
                }
            }
        }
    }
 
   CONFIG_FILE.write_text(json.dumps(config, indent=2))
    print(f"✅ Config written to {CONFIG_FILE}")
    print(f"✅ IMAP configured: host={imap_host}, user={imap_user}"))
 
 
# ── Gateway manager ──────────────────────────────────────────────────────────
class NanobotGateway:
    def __init__(self):
        self.process = None
        self.status = "stopped"
 
    async def start(self):
        if self.process and self.process.returncode is None:
            return
        print("🐈 Starting nanobot gateway...")

     # Pass ALL environment variables explicitly to the subprocess
        env = os.environ.copy()   
     
     self.process = await asyncio.create_subprocess_exec(
            "nanobot", "gateway",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env
        )
        self.status = "running"
        asyncio.create_task(self._stream_logs())
        print(f"✅ nanobot gateway started (pid {self.process.pid})")
 
    async def stop(self):
        if not self.process or self.process.returncode is not None:
            return
        print("🛑 Stopping nanobot gateway...")
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=10)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()
        self.status = "stopped"
        print("✅ nanobot gateway stopped")
 
    async def _stream_logs(self):
        try:
            while self.process and self.process.stdout:
                line = await self.process.stdout.readline()
                if not line:
                    break
                print(f"[nanobot] {line.decode('utf-8', errors='replace').rstrip()}")
        except asyncio.CancelledError:
            return
        if self.process and self.status == "running":
            self.status = "error"
            print("⚠️ nanobot gateway exited unexpectedly")
 
 
gateway = NanobotGateway()
 
 
# ── Routes ───────────────────────────────────────────────────────────────────
async def health(request: Request):
    """Railway health check endpoint — must return 200."""
    return JSONResponse({"status": "ok", "gateway": gateway.status})
 
 
async def homepage(request: Request):
    """Simple status page."""
    html = f"""
    <html>
    <head><title>Riley - nanobot</title></head>
    <body style="font-family:sans-serif;padding:2rem;background:#0f0f0f;color:#eee;">
        <h1>🐈 Riley is running</h1>
        <p>Gateway status: <strong>{gateway.status}</strong></p>
        <p>Telegram bot is active and listening for messages.</p>
        <p style="color:#888;font-size:0.85rem;">Powered by nanobot on Railway</p>
    </body>
    </html>
    """
    return HTMLResponse(html)
 
 
# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    write_config()
    await gateway.start()
    try:
        yield
    finally:
        await gateway.stop()
 
 
# ── App ───────────────────────────────────────────────────────────────────────
app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/health", health),
    ],
    lifespan=lifespan,
)
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
 
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
 
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
 
    def handle_signal():
        loop.create_task(gateway.stop())
        server.should_exit = True
 
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)
 
    loop.run_until_complete(server.serve())
