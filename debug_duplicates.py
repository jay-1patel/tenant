#!/usr/bin/env python3

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def _remove_duplicate_words(text: str) -> str:
    """Remove consecutive duplicate words."""
    print(f"Processing text: '{text}'")
    
    # First normalize dashes and special characters to make comparison easier
    normalized_text = text.replace('\u2013', '-').replace('\u2014', '-')
    print(f"Normalized text: '{normalized_text}'")
    
    words = normalized_text.split()
    print(f"Words: {words}")
    
    cleaned_words = []
    
    for i, word in enumerate(words):
        # Normalize word for comparison
        normalized_word = word.lower().strip('.,()-')
        print(f"  Word {i}: '{word}' -> normalized: '{normalized_word}'")
        
        if i > 0:
            prev_word = words[i-1]
            prev_normalized = prev_word.lower().strip('.,()-')
            print(f"    comparing with previous: '{prev_word}' -> normalized: '{prev_normalized}'")
            
            # Skip word if it's the same as previous (case insensitive and ignoring common punctuation)
            if normalized_word == prev_normalized:
                print(f"    -> DUPLICATE FOUND, skipping")
                continue
        print(f"    -> Keeping word")
        cleaned_words.append(words[i])  # Use original word, not normalized
    
    result = ' '.join(cleaned_words)
    print(f"Result: '{result}'")
    return result

# Test cases
test_cases = [
    "Sales Executive Sales 2-4 years Mumbai",
    "QA Tester Tester 1-2 years Bhavnagar", 
    "IT Manager Manager 0-2 years Bhavnagar",
    "Senior HR Executive HR 3-5 years Bhavnagar"
]

for test in test_cases:
    print(f"\n--- TEST: {test} ---")
    result = _remove_duplicate_words(test)
    print(f"Final: '{result}'\n")