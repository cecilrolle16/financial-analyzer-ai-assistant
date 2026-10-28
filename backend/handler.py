"""API for uploading a financial PDF and returning an AI review."""

import base64
import json
import os
import re
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from analysis import SYSTEM_PROMPT, USER_PROMPT, parse_model_output

UPLOAD_BUCKET = os.environ.get("UPLOAD_BUCKET", "")
MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
PRESIGN_EXPIRY = int(os.environ.get("PRESIGN_EXPIRY", "300"))
MAX_BYTES = int(os.environ.get("MAX_BYTES", "4500000"))
KEY_RE = re.compile(
    r"^uploads/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf$"
)

_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
s3 = boto3.client("s3", region_name=_REGION)
bedrock = boto3.client("bedrock-runtime", region_name=_REGION)


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "")
    path = path.rstrip("/") or "/"

    try:
        if method == "GET" and path == "/health":
            return _response(200, {"status": "healthy"})
        if method == "GET" and path == "/about":
            return _response(200, {
                "project": "Financial Document Analyzer",
                "purpose": (
                    "Review different kinds of financial documents, point out problems, "
                    "and suggest understandable next steps."
                ),
            })
        if method == "POST" and path == "/upload-url":
            return _upload_url(event)
        if method == "POST" and path == "/analyze":
            return _analyze(event)
        return _response(404, {"error": "Not found."})
    except json.JSONDecodeError:
        return _response(400, {"error": "The request body must be JSON."})
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "Unknown")
        print(f"AWS error {code} on {method} {path}")
        if code in ("NoSuchKey", "404", "NotFound"):
            return _response(404, {"error": "That upload was not found. Choose the PDF again."})
        if code in ("ValidationException", "AccessDeniedException"):
            return _response(502, {
                "error": "The document could not be reviewed. Check that the AI model is enabled.",
                "error_code": code,
            })
        if code == "ThrottlingException":
            return _response(429, {"error": "The analyzer is busy. Wait a moment and try again."})
        return _response(502, {"error": "The analyzer hit a service error.", "error_code": code})
    except BotoCoreError as err:
        print(f"AWS connection error: {err}")
        return _response(502, {"error": "The analyzer could not reach AWS. Try again."})


def _upload_url(event):
    if not UPLOAD_BUCKET:
        return _response(500, {"error": "Upload storage is not configured."})

    body = _body(event)
    filename = body.get("filename")
    content_type = str(body.get("contentType") or "").split(";")[0].strip().lower()
    size = body.get("sizeBytes")

    if not isinstance(filename, str) or not filename.lower().endswith(".pdf"):
        return _response(400, {"error": "Choose a PDF. Other file types are not accepted."})
    if content_type != "application/pdf":
        return _response(400, {"error": "The file must be a PDF."})
    if isinstance(size, bool) or not isinstance(size, int) or size < 1 or size > MAX_BYTES:
        return _response(400, {
            "error": "The PDF must be 4.5 MB or smaller.",
        })

    key = f"uploads/{uuid.uuid4()}.pdf"
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": UPLOAD_BUCKET,
            "Key": key,
            "ContentType": "application/pdf",
            "ContentLength": size,
        },
        ExpiresIn=PRESIGN_EXPIRY,
    )
    return _response(200, {
        "uploadUrl": upload_url,
        "key": key,
        "expiresIn": PRESIGN_EXPIRY,
        "headers": {"Content-Type": "application/pdf"},
    })


def _analyze(event):
    if not UPLOAD_BUCKET:
        return _response(500, {"error": "Upload storage is not configured."})

    key = _body(event).get("key")
    if not isinstance(key, str) or not KEY_RE.match(key):
        return _response(400, {"error": "That document key is not valid. Upload the PDF again."})

    head = s3.head_object(Bucket=UPLOAD_BUCKET, Key=key)
    size = head.get("ContentLength", 0)
    if size < 1 or size > MAX_BYTES:
        return _response(400, {"error": "That PDF is empty or larger than the 4 MB limit."})

    obj = s3.get_object(Bucket=UPLOAD_BUCKET, Key=key)
    pdf_bytes = obj["Body"].read()
    s3.delete_object(Bucket=UPLOAD_BUCKET, Key=key)

    if not pdf_bytes.startswith(b"%PDF"):
        return _response(400, {"error": "That file is not a PDF."})

    model_reply = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{
            "role": "user",
            "content": [
                {
                    "document": {
                        "format": "pdf",
                        "name": "financial-document",
                        "source": {"bytes": pdf_bytes},
                    }
                },
                {"text": USER_PROMPT},
            ],
        }],
        inferenceConfig={"maxTokens": 1800, "temperature": 0},
    )
    parts = model_reply.get("output", {}).get("message", {}).get("content", [])
    text = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not text.strip():
        return _response(502, {"error": "The review came back empty. Try again."})
    return _response(200, parse_model_output(text))


def _body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded") and raw:
        raw = base64.b64decode(raw).decode("utf-8")
    if not raw:
        return {}
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise json.JSONDecodeError("Expected an object", raw, 0)
    return loaded


def _response(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
