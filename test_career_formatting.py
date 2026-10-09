#!/usr/bin/env python3

import sys
import re
from pathlib import Path

# Ensure proper encoding for stdout
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add the backend directory to the path
backend_path = Path(__file__).resolve().parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

# Import the formatting functions
try:
    from services.intent_answers import _format_careers_content, _format_job_posting, _parse_job_info, _build_job_string, _remove_duplicate_words
    print("Successfully imported formatting functions")
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

# Test raw text from the screenshot - use regular dashes for now
raw_careers_text = """Sales Executive Sales 2-4 years Mumbai
BDM Executive Sales 2-5 years Mumbai
Back Office Executive Sales 0-2 years Bhavnagar
AEO/SEO Executive Sales 2-4 years Delhi
QA Tester Tester 1-2 years Bhavnagar
Senior Accountant Account 3-5 years Bhavnagar
Senior HR Executive HR 3-5 years Bhavnagar
Sales Executive Sales 2-4 years Bhavnagar
IT Manager Manager 0-2 years Bhavnagar
UI & UX Designer Design 1-2 years Bhavnagar
L1 Support Executive Support 2-4 years Delhi
L2 Support Executive Support 2-4 years Delhi"""

print("\n" + "="*50)
print("RAW INPUT:")
print("="*50)
print(raw_careers_text)

print("\n" + "="*50)
print("TESTING INDIVIDUAL FUNCTIONS:")
print("="*50)

# Test duplicate removal
test_text = "Sales Executive Sales 2-4 years Mumbai"
cleaned = _remove_duplicate_words(test_text)
print(f"Remove duplicates: '{test_text}' -> '{cleaned}'")

# Test job parsing
job_text = "Sales Executive 2-4 years Mumbai"
parsed = _parse_job_info(job_text)
print(f"Parsed job: {parsed}")

built = _build_job_string(parsed)
print(f"Built string: '{built}'")

# Test job posting formatting
formatted_job = _format_job_posting("Sales Executive Sales 2-4 years Mumbai")
print(f"Formatted job: '{formatted_job}'")

print("\n" + "="*50)
print("TESTING FULL CAREERS FORMATTING:")
print("="*50)

# Test the full careers formatting
formatted_result = _format_careers_content(raw_careers_text)
print(formatted_result)

print("\n" + "="*50)
print("EXPECTED OUTPUT (similar format):")
print("="*50)
expected = """Current Job Openings

- Sales Executive - 2-4 years experience (Mumbai)
- BDM Executive Sales - 2-5 years experience (Mumbai)
- Back Office Executive - 0-2 years experience (Bhavnagar)
- AEO/SEO Executive - 2-4 years experience (Delhi)
- QA Tester - 1-2 years experience (Bhavnagar)
- Senior Accountant - 3-5 years experience (Bhavnagar)
- Senior HR Executive - 3-5 years experience (Bhavnagar)
- Sales Executive - 2-4 years experience (Bhavnagar)
- IT Manager - 0-2 years experience (Bhavnagar)
- UI & UX Designer - 1-2 years experience (Bhavnagar)
- L1 Support Executive - 2-4 years experience (Delhi)
- L2 Support Executive - 2-4 years experience (Delhi)"""

print(expected)