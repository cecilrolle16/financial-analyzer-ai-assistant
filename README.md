# Financial Analyzer Ai Assistant

A public web app that reviews financial PDFs. It works across document types: bank statements, pay stubs, invoices, bills, tax forms, loan documents, credit-card statements, and similar files.

The page asks Amazon Bedrock (Claude Haiku 4.5) for a plain-language summary, the important figures, problems worth noticing, and next steps. The result always includes a notice that this is not financial, tax, legal, or investment advice.

This project is separate from the mortgage FAQ assistant.

## How a review works

```
Browser  →  CloudFront  →  S3 website
    │
    ├─ POST /upload-url
    ├─ PUT  the PDF to a private S3 bucket (presigned URL, 5 minutes)
    └─ POST /analyze
              │
              ▼
           Lambda  →  Amazon Bedrock
              │
              ▼
           JSON findings, then the PDF is deleted
```

The upload bucket is private. Leftover files expire after one day. The Lambda role can only read, write, and delete objects under `uploads/`, and it can invoke only Claude Haiku 4.5.

## Project files

| Path | Role |
| --- | --- |
| `app.py` | Original FastAPI prototype on the EC2 instance |
| `backend/handler.py` | Lambda API |
| `backend/analysis.py` | Shared rules for reading the model reply |
| `frontend/` | Upload page |
| `template.yaml` | AWS SAM stack |
| `tests/test_analyzer.py` | Unit tests, with AWS mocked |

## Run the tests

```powershell
python -m unittest tests.test_analyzer
```

## Deploy

Deployment creates the S3 buckets, Lambda function, HTTP API, IAM role, and CloudFront distribution in `us-east-1`. Run it only after that change is approved.

```powershell
sam build
sam deploy
aws s3 sync frontend s3://financial-analyzer-site-ACCOUNT-us-east-1 --delete
```

Replace `ACCOUNT` with the AWS account id. The stack output `SiteUrl` is the public HTTPS address. CloudFront can take a few minutes to serve the page.

The model must already be enabled for the account in Amazon Bedrock. The mortgage FAQ project used the same Claude Haiku 4.5 inference profile.
