def main() -> None:
    import uvicorn

    uvicorn.run("ad_optimizer.api:app", host="127.0.0.1", port=8000, workers=1)
