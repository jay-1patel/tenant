"""
Fast QA Spelling and Lint Defect Scanner
Scans clients, shared, backend for typos, spelling mistakes, and text defects.
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

EXTS = ('.json', '.md', '.py')
DIRS = ['clients', 'shared', 'backend/services', 'backend/routes', 'backend/faq', 'backend/bots']

IGNORE_PARTS = ['.git', '__pycache__', 'node_modules', '.pytest_cache', 'models', 'admin_build', 'uploaded_files', '.venv']

TYPOS = {
    'eligibiluty': 'eligibility',
    'eligiblity': 'eligibility',
    'compalint': 'complaint',
    'complaintes': 'complaints',
    'repoding': 'responding',
    'excpects': 'expects',
    'tetant': 'tenant',
    'recieved': 'received',
    'seperate': 'separate',
    'untill': 'until',
    'succesful': 'successful',
    'goverment': 'government',
    'enviroment': 'environment',
    'calender': 'calendar',
    'whatapp': 'WhatsApp',
    'procuts': 'products',
    'brocure': 'brochure',
    'catelogue': 'catalogue',
    'inquieries': 'inquiries',
    'accomodate': 'accommodate',
    'occured': 'occurred',
    'truely': 'truly',
}

def scan():
    matches = []
    for d in DIRS:
        if not os.path.exists(d):
            continue
        for root, _, files in os.walk(d):
            if any(ign in root for ign in IGNORE_PARTS):
                continue
            for file in files:
                if file.endswith(EXTS):
                    fp = os.path.join(root, file)
                    try:
                        with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        for typo, correct in TYPOS.items():
                            for m in re.finditer(rf'\b{re.escape(typo)}\b', content, re.IGNORECASE):
                                line_no = content[:m.start()].count('\n') + 1
                                matches.append((fp, line_no, m.group(), correct))
                    except Exception as e:
                        print(f"Error reading {fp}: {e}")

    print(f"Total spelling defects detected: {len(matches)}")
    for fp, lno, found, corr in matches:
        print(f"  {fp}:{lno} -> Found '{found}', suggested correction: '{corr}'")

if __name__ == '__main__':
    scan()
