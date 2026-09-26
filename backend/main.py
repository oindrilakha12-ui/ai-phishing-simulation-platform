from fastapi import FastAPI

app = FastAPI(title="AI Phishing Simulation Platform API")


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "message": "AI Phishing Simulation Platform API is running"
    }