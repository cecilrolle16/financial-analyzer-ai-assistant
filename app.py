"""Original on-server prototype. The public app is backend/handler.py."""

from fastapi import FastAPI, File, UploadFile

app = FastAPI()


@app.get("/")
def home():
    return {"message": "Financial Analyzer Running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/about")
def about():
    return {
        "project": "Financial Document Analyzer",
        "purpose": (
            "Review different kinds of financial documents, point out problems, "
            "and suggest understandable next steps."
        ),
    }


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    contents = await file.read()
    return {
        "message": "File received",
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": len(contents),
    }
