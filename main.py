from fastapi import FastAPI

app = FastAPI(title="Pakgat Voucher System")

@app.get("/")
def home():
    return {
        "status": "running",
        "service": "Pakgat Voucher System",
        "version": "1.0"
    }

@app.get("/health")
def health():
    return {"ok": True}
