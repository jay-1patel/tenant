#!/usr/bin/env python3

import re

def _remove_duplicate_words(text: str) -> str:
    """Remove duplicate words from job titles."""
    if not text or not text.strip():
        return text
        
    words = text.split()
    
    if len(words) <= 1:
        return text
    
    print(f"Starting with: {words}")
    
    # First, remove consecutive duplicates
    no_consecutive_dups = []
    for i, word in enumerate(words):
        if i > 0 and word.lower() == words[i-1].lower():
            continue
        no_consecutive_dups.append(word)
    
    words = no_consecutive_dups
    print(f"After consecutive removal: {words}")
    
    # Find the title portion (before experience/location)
    title_words = []
    for word in words:
        # Check if this word looks like experience info or location
        if (re.match(r'^[0-9]+[-][0-9]+$', word) or 
            re.match(r'^[0-9]+$', word) or 
            word.lower() in ['years', 'year', 'yrs', 'yr', 'experience', 'exp'] or
            word in ['Mumbai', 'Delhi', 'Bhavnagar', 'Bangalore', 'Chennai', 
                    'Kolkata', 'Pune', 'Ahmedabad', 'Hyderabad', 'Surat', 
                    'Jaipur', 'Lucknow']):
            break
        title_words.append(word)
    
    print(f"Title words: {title_words}")
    print(f"Remaining words: {words[len(title_words):]}")
    
    # If we have at least 2 title words and the last one duplicates an earlier one, remove it
    if len(title_words) >= 2:
        last_title_word = title_words[-1].lower()
        print(f"Last title word: {last_title_word}")
        # Check if the last word in the title appears earlier in the title
        for i in range(len(title_words) - 1):
            print(f"Checking {title_words[i].lower()} vs {last_title_word}")
            if title_words[i].lower() == last_title_word:
                print("MATCH FOUND - removing last word")
                title_words = title_words[:-1]  # Remove the last word
                break
    
    print(f"Final title words: {title_words}")
    
    # Reconstruct: title words + remaining words
    remaining_words = words[len(title_words):]
    final_words = title_words + remaining_words
    
    result = ' '.join(final_words)
    print(f"Final result: {result}")
    return result

# Test
result = _remove_duplicate_words('Sales Executive Sales 2-4 years Mumbai')
print(f"Final: {result}")