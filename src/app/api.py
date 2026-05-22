from fastapi import FastAPI

app = FastAPI(title="Vendor Comparison Platform")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
