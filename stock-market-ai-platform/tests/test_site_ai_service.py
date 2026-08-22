import json
import os
import unittest
from unittest.mock import patch

from webapp.services.site_ai_service import (
    SiteAIConfigurationError,
    _extract_output_text,
    build_input,
)


class SiteAIServiceTests(unittest.TestCase):
    def test_build_input_includes_page_and_question(self):
        value = build_input(
            "What does this chart mean?",
            {"title": "V8 Dashboard", "path": "/dashboard", "visible_text": "Holdout starts September 1."},
            [{"role": "assistant", "content": "Earlier answer"}],
        )
        self.assertIn("V8 Dashboard", value)
        self.assertIn("/dashboard", value)
        self.assertIn("Holdout starts September 1.", value)
        self.assertIn("What does this chart mean?", value)

    def test_build_input_rejects_blank_question(self):
        with self.assertRaises(ValueError):
            build_input("   ", {})

    def test_output_parser_handles_responses_shape(self):
        payload = {"output": [{"content": [{"type": "output_text", "text": "A useful answer."}]}]}
        self.assertEqual(_extract_output_text(payload), "A useful answer.")

    def test_client_uses_text_content_not_html(self):
        source = open("webapp/static/js/site_ai_assistant.js", encoding="utf-8").read()
        self.assertIn("node.textContent = content", source)
        self.assertNotIn("node.innerHTML = content", source)
        self.assertIn('location.pathname.startsWith(prefix)', source)
        self.assertIn('path: "/account", visible_text: ""', source)

    def test_global_injection_and_endpoint_are_registered(self):
        source = open("webapp/app.py", encoding="utf-8").read()
        self.assertIn("/static/js/site_ai_assistant.js", source)
        self.assertIn("/static/css/site_ai_assistant.css", source)
        self.assertIn('@app.post("/api/site-assistant")', source)


if __name__ == "__main__":
    unittest.main()
