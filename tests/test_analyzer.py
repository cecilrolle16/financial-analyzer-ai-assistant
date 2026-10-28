"""Tests for the review parser and the Lambda routes. No AWS calls."""

import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, BACKEND)

try:
    import boto3  # noqa: F401
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    exceptions = types.ModuleType("botocore.exceptions")

    class ClientError(Exception):
        def __init__(self, error_response, operation_name):
            super().__init__(operation_name)
            self.response = error_response

    class BotoCoreError(Exception):
        pass

    exceptions.ClientError = ClientError
    exceptions.BotoCoreError = BotoCoreError
    botocore = types.ModuleType("botocore")
    botocore.exceptions = exceptions
    sys.modules["botocore"] = botocore
    sys.modules["botocore.exceptions"] = exceptions
    boto3_mod = types.ModuleType("boto3")
    boto3_mod.client = lambda *args, **kwargs: MagicMock()
    sys.modules["boto3"] = boto3_mod

os.environ["UPLOAD_BUCKET"] = "test-uploads"
os.environ["BEDROCK_MODEL_ID"] = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

import analysis  # noqa: E402
import handler  # noqa: E402


def _event(method, path, body=None):
    event = {"requestContext": {"http": {"method": method, "path": path}}, "rawPath": path}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


class ParseTests(unittest.TestCase):
    def test_bank_statement_and_invoice_use_the_same_shape(self):
        statement = analysis.parse_model_output(json.dumps({
            "documentType": "Bank statement",
            "summary": "Checking account for May.",
            "keyFigures": [{"label": "Ending balance", "value": "$1,240.10"}],
            "problems": [{
                "severity": "high",
                "title": "Overdraft fee",
                "detail": "A $35 overdraft fee posted on May 3.",
            }],
            "recommendations": ["Ask the bank to refund the overdraft fee."],
        }))
        invoice = analysis.parse_model_output(json.dumps({
            "documentType": "Vendor invoice",
            "summary": "Invoice 1044 is unpaid.",
            "keyFigures": [{"label": "Amount due", "value": "$880.00"}],
            "problems": [{
                "severity": "medium",
                "title": "Due date passed",
                "detail": "Payment was due April 1.",
            }],
            "recommendations": ["Pay the open balance or confirm it was already sent."],
        }))
        for review, kind in ((statement, "Bank statement"), (invoice, "Vendor invoice")):
            self.assertEqual(review["documentType"], kind)
            self.assertIn("disclaimer", review)
            self.assertTrue(review["problems"])
            self.assertTrue(review["recommendations"])

    def test_fenced_and_broken_text(self):
        fenced = analysis.parse_model_output(
            '```json\n{"documentType":"Pay stub","summary":"Wages for the last period.",'
            '"keyFigures":[],"problems":[],"recommendations":["Keep this with your tax papers."]}\n```'
        )
        self.assertEqual(fenced["documentType"], "Pay stub")
        self.assertEqual(fenced["problems"], [])

        fallback = analysis.parse_model_output("not json")
        self.assertEqual(fallback["documentType"], "Financial document")
        self.assertIn("clear summary", fallback["summary"])
        self.assertEqual(fallback["disclaimer"], analysis.DISCLAIMER)

    def test_unknown_severity_is_medium(self):
        review = analysis.parse_model_output(json.dumps({
            "documentType": "Bill",
            "summary": "A utility bill.",
            "keyFigures": [{"label": "", "value": "$1"}],
            "problems": [{"severity": "urgent", "title": "Late fee", "detail": "A late fee was added."}],
            "recommendations": ["  "],
        }))
        self.assertEqual(review["problems"][0]["severity"], "medium")
        self.assertEqual(review["keyFigures"], [])
        self.assertEqual(review["recommendations"], [])


class HandlerTests(unittest.TestCase):
    def test_health_and_about(self):
        health = json.loads(handler.lambda_handler(_event("GET", "/health"), None)["body"])
        about = json.loads(handler.lambda_handler(_event("GET", "/about"), None)["body"])
        self.assertEqual(health["status"], "healthy")
        self.assertIn("financial documents", about["purpose"])

    def test_upload_url_rejects_non_pdf_and_signs_a_private_key(self):
        rejected = handler.lambda_handler(
            _event("POST", "/upload-url", {
                "filename": "notes.docx",
                "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "sizeBytes": 100,
            }),
            None,
        )
        self.assertEqual(rejected["statusCode"], 400)

        handler.s3 = MagicMock()
        handler.s3.generate_presigned_url.return_value = "https://example.com/upload"
        accepted = handler.lambda_handler(
            _event("POST", "/upload-url", {
                "filename": "card-statement.pdf",
                "contentType": "application/pdf",
                "sizeBytes": 1200,
            }),
            None,
        )
        body = json.loads(accepted["body"])
        self.assertEqual(accepted["statusCode"], 200)
        self.assertRegex(body["key"], handler.KEY_RE)
        params = handler.s3.generate_presigned_url.call_args.kwargs["Params"]
        self.assertEqual(params["ContentType"], "application/pdf")
        self.assertEqual(params["ContentLength"], 1200)
        self.assertTrue(params["Key"].startswith("uploads/"))

    def test_analyze_rejects_a_foreign_key_and_reviews_a_pdf(self):
        denied = handler.lambda_handler(
            _event("POST", "/analyze", {"key": "../secrets.pdf"}),
            None,
        )
        self.assertEqual(denied["statusCode"], 400)

        handler.s3 = MagicMock()
        handler.bedrock = MagicMock()
        handler.s3.head_object.return_value = {"ContentLength": 20}
        handler.s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"%PDF-1.7 sample")}
        handler.bedrock.converse.return_value = {
            "output": {"message": {"content": [{"text": json.dumps({
                "documentType": "Loan statement",
                "summary": "A personal loan with a remaining balance.",
                "keyFigures": [{"label": "Balance", "value": "$4,200"}],
                "problems": [{
                    "severity": "high",
                    "title": "Past due",
                    "detail": "The statement shows a past-due amount.",
                }],
                "recommendations": ["Pay the past-due amount or contact the lender."],
            })}]}}
        }
        result = handler.lambda_handler(
            _event("POST", "/analyze", {
                "key": "uploads/11111111-1111-1111-1111-111111111111.pdf",
            }),
            None,
        )
        body = json.loads(result["body"])
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(body["documentType"], "Loan statement")
        self.assertEqual(body["problems"][0]["title"], "Past due")
        handler.s3.delete_object.assert_called_once()
        self.assertEqual(handler.bedrock.converse.call_args.kwargs["modelId"], handler.MODEL_ID)

    def test_analyze_rejects_a_file_that_is_not_a_pdf(self):
        handler.s3 = MagicMock()
        handler.s3.head_object.return_value = {"ContentLength": 5}
        handler.s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"hello")}
        result = handler.lambda_handler(
            _event("POST", "/analyze", {
                "key": "uploads/22222222-2222-2222-2222-222222222222.pdf",
            }),
            None,
        )
        self.assertEqual(result["statusCode"], 400)
        handler.s3.delete_object.assert_called_once()


if __name__ == "__main__":
    unittest.main()
