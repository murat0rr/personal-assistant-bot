from fastapi import FastAPI

app = FastAPI(title="Личный ассистент API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
