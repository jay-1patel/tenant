"""Profile-driven answers for informational intents (panels).

Menu rows like Technologies, Projects, Careers and Benefits have no flow and
no backend service: their entire content is tenant data. The answer text lives
in the tenant profile (vertical defaults -> clients/<id>/config.json ->
published DB version), so a tenant that publishes new text changes the panel
without a code change — nothing here is brand-specific.

Resolution never raises: every function returns None when the profile layer is
unavailable or the tenant configured no answer, and the caller then falls
through to the existing pipeline unchanged.
"""
import logging
import re
from typing import Dict

logger = logging.getLogger("services.intent_answers")

# Import response formatter for nice formatting
try:
    from services.response_formatters import WhatsAppFormatter, MessageType, smart_format
    RESPONSE_FORMATTER_AVAILABLE = True
except ImportError:
    RESPONSE_FORMATTER_AVAILABLE = False


def _profile(tenant_id=None, wa_id: str = ""):
    """The tenant profile, or None. Same defensive pattern as flow_runner."""
    try:
        import sys as _sys
        from pathlib import Path as _Path

        root = str(_Path(__file__).resolve().parents[2])
        if root not in _sys.path:
            _sys.path.insert(0, root)

        from shared.tenancy.loader import get_tenant_profile
        from shared.tenancy.resolver import resolve_tenant_for_user

        return get_tenant_profile(tenant_id or resolve_tenant_for_user(wa_id or ""))
    except Exception as exc:  # pragma: no cover - defensive by design
        logger.debug("intent_answers: profile unavailable (%s)", exc)
        return None


def _answered_intents(profile) -> list:
    """Active intents that carry answer text, in profile order."""
    if profile is None:
        return []
    active = {i.name for i in profile.active_intents()}
    return [
        i for i in profile.intents
        if i.name in active and (i.answer or "").strip()
    ]


def answer_for_button(wa_id: str, button_id: str, tenant_id=None) -> str | None:
    """Answer text for a tapped profile menu row, or None.

    Dispatches on the button id (load-bearing, stable) via its ``intent``
    field — the row's title never enters the decision.
    """
    if not button_id:
        return None
    profile = _profile(tenant_id, wa_id)
    if profile is None:
        return None
    for b in profile.menu.buttons:
        if b.id == button_id and getattr(b, "intent", None):
            return answer_for_intent(wa_id, b.intent, tenant_id=tenant_id or profile.tenant_id)
    return None


def answer_for_intent(wa_id: str, intent_name: str, tenant_id=None) -> str | None:
    """Answer text for a named intent (also serves registry buttons, whose ids
    match intent names by convention: projects, technologies, careers,
    benefits). None unless the intent is active AND has answer text."""
    if not intent_name:
        return None
    profile = _profile(tenant_id, wa_id)
    if profile is None:
        return None
    for intent in _answered_intents(profile):
        if intent.name == intent_name:
            raw_answer = intent.answer.strip()
            return _format_nice_answer(raw_answer, intent_name)
    return None


def _format_nice_answer(answer: str, intent_name: str) -> str:
    """
    Format answer text with proper structure based on intent type.
    
    This ensures that menu content like Technologies, Careers, etc. is properly
    formatted with emojis, bullet points, and good readability.
    """
    if not answer or not answer.strip():
        return answer or ""
    
    # Skip formatting if new formatter not available
    if not RESPONSE_FORMATTER_AVAILABLE:
        return answer
    
    try:
        # Determine message type based on intent
        message_type = _get_message_type_for_intent(intent_name)
        
        # Create formatter
        formatter = WhatsAppFormatter()
        
        # Apply formatting
        formatted_answer = formatter.format(answer, message_type=message_type)
        
        # Additional specific formatting for certain content types
        if intent_name.lower() in ["careers", "job", "jobs", "opening", "vacancy"]:
            formatted_answer = _format_careers_content(formatted_answer)
        elif intent_name.lower() in ["technologies", "tech", "technology"]:
            formatted_answer = _format_technologies_content(formatted_answer)
        
        return formatted_answer
        
    except Exception as e:
        logger.debug(f"Failed to format intent answer {intent_name}: {e}")
        return answer


def _get_message_type_for_intent(intent_name: str):
    """Get appropriate message type for intent."""
    intent_lower = intent_name.lower()
    
    type_mapping = {
        "greeting": MessageType.GREETING,
        "welcome": MessageType.GREETING,
        "about": MessageType.FAQ_ANSWER,
        "company": MessageType.FAQ_ANSWER,
        "careers": MessageType.FAQ_ANSWER,
        "technologies": MessageType.FAQ_ANSWER,
        "projects": MessageType.FAQ_ANSWER,
        "benefits": MessageType.FAQ_ANSWER,
        "contact": MessageType.SUPPORT_RESPONSE,
        "support": MessageType.SUPPORT_RESPONSE,
        "menu": MessageType.INSTRUCTIONS,
        "help": MessageType.INSTRUCTIONS,
    }
    
    return type_mapping.get(intent_lower, MessageType.FAQ_ANSWER)


def _format_careers_content(text: str) -> str:
    """Format careers/job listings with nice structure."""
    if not text or not text.strip():
        return text
    
    # Check if this is already well formatted (has proper bullet points)
    if _has_proper_formatting(text):
        # Just enhance with emoji header if not already present
        if not text.strip().startswith('💼'):
            text = _add_careers_header(text)
        return text
    
    # Split by newlines or commas
    if ',' in text and '\n' not in text:
        lines = [line.strip() for line in text.split(',')]
    else:
        lines = [line.strip() for line in text.split('\n')]
    
    formatted_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped:
            # Always process as job listing for careers content
            formatted_lines.append(_format_job_posting(stripped))
        else:
            formatted_lines.append('')
    
    result = '\n'.join(formatted_lines)
    # Add careers header with emoji if not already present
    if not result.strip().startswith('💼'):
        result = _add_careers_header(result)
    
    return result


def _format_technologies_content(text: str) -> str:
    """Format technologies content with bullet points."""
    if not text or not text.strip():
        return text
    
    # Check if this is already well formatted
    if _has_proper_formatting(text):
        # Just enhance with header
        text = _add_technologies_header(text)
        return text
    
    # Convert comma-separated lists to newlines
    text = re.sub(r',\s+', '\n', text)
    
    # Ensure each line starts with a bullet if it doesn't have one
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped:
            # Check if already starts with bullet or number
            if not re.match(r'^[•\-*\d\.]+', stripped) and not _is_header_line(stripped):
                stripped = f"• {stripped}"
            formatted_lines.append(stripped)
        else:
            formatted_lines.append('')
    
    result = '\n'.join(formatted_lines)
    # Add technologies header with emoji
    return _add_technologies_header(result)


def _is_job_posting(text: str) -> bool:
    """Check if text looks like a job posting."""
    # Common job posting patterns
    patterns = [
        r'^[A-Z][a-z]+\s+[A-Z][a-z]+',  # "Sales Executive"
        r'^[A-Z][a-z]+\s+[A-Z][a-z]+\s+[A-Z][a-z]+',  # "Senior Sales Executive"
        r'^[0-9]+[+-]?[0-9]*\s+year',  # "2-4 years"
        r'years\s+experience',
        r'[A-Z][a-z]+\s+-\s+',  # "Sales - Mumbai"
    ]
    
    # Check if any pattern matches at the start
    for pattern in patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return True
    
    # Check for common job title words
    job_keywords = ['executive', 'manager', 'engineer', 'developer', 'designer', 
                   'specialist', 'officer', 'assistant', 'analyst', 'coordinator']
    
    return any(keyword in text.lower() for keyword in job_keywords)


def _format_job_posting(text: str) -> str:
    """Format a single job posting."""
    if not text or not text.strip():
        return text
    
    text = text.strip()
    
    # Remove duplicate words (e.g., "Sales Executive Sales" -> "Sales Executive")
    text = _remove_duplicate_words(text)
    
    # Parse job components
    job_info = _parse_job_info(text)
    
    # Format based on parsed information
    formatted_text = _build_job_string(job_info)
    
    # Add bullet if not already present
    if not formatted_text.startswith('•'):
        formatted_text = f"• {formatted_text}"
    
    return formatted_text


def _has_proper_formatting(text: str) -> bool:
    """Check if text already has proper formatting."""
    lines = text.split('\n')
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('•') and not stripped.startswith('•'):
            # Check if it looks like a header
            if not _is_header_line(stripped):
                return False
    return True


def _remove_duplicate_words(text: str) -> str:
    """Remove duplicate words from job titles."""
    if not text or not text.strip():
        return text
        
    words = text.split()
    
    if len(words) <= 1:
        return text
    
    # First, remove consecutive duplicates
    no_consecutive_dups = []
    for i, word in enumerate(words):
        if i > 0 and word.lower() == words[i-1].lower():
            continue
        no_consecutive_dups.append(word)
    
    words = no_consecutive_dups
    
    # Find the title portion (before experience/location) and identify which words to keep
    title_end_index = len(words)  # default to all words being title
    
    for i, word in enumerate(words):
        # Check if this word looks like experience info or location
        if (re.match(r'^[0-9]+[-][0-9]+$', word) or 
            re.match(r'^[0-9]+$', word) or 
            word.lower() in ['years', 'year', 'yrs', 'yr', 'experience', 'exp'] or
            word in ['Mumbai', 'Delhi', 'Bhavnagar', 'Bangalore', 'Chennai', 
                    'Kolkata', 'Pune', 'Ahmedabad', 'Hyderabad', 'Surat', 
                    'Jaipur', 'Lucknow']):
            title_end_index = i
            break
    
    # Check for duplicates in the title portion
    title_words = words[:title_end_index]
    
    # Remove duplicates from title: if the last word is a duplicate of any earlier word, remove it
    if len(title_words) >= 2:
        last_word = title_words[-1].lower()
        for i in range(len(title_words) - 1):
            if title_words[i].lower() == last_word:
                # Remove the last word from title_words
                title_words = title_words[:-1]
                break
    
    # Reconstruct: cleaned title words + remaining words
    remaining_words = words[title_end_index:]
    final_words = title_words + remaining_words
    
    return ' '.join(final_words)


def _parse_job_info(text: str) -> Dict[str, str]:
    """Parse job text into structured components."""
    # Initialize result
    result = {
        'title': text,
        'experience': '',
        'location': '',
        'type': ''
    }
    
    # Patterns to extract information
    # Experience pattern: "2-4 years", "0-2 years", "1–2 years", etc.
    # Use normalized text for pattern matching
    normalized_text = text.replace('–', '-').replace('—', '-')
    exp_pattern = r'([0-9]+[-][0-9]+|[0-9]+[+-]?[0-9]*)\s*(?:years?|yrs?|exp|experience)'
    exp_match = re.search(exp_pattern, normalized_text, re.IGNORECASE)
    if exp_match:
        result['experience'] = exp_match.group(1).replace('–', '-').replace('—', '-')
    else:
        # Try again with a simpler pattern looking for number-number
        exp_pattern_simple = r'([0-9]+)[\-–—]([0-9]+)'
        exp_match_simple = re.search(exp_pattern_simple, text)
        if exp_match_simple:
            result['experience'] = f"{exp_match_simple.group(1)}-{exp_match_simple.group(2)}"
    
    # Location pattern: City names at the end (Mumbai, Delhi, Bhavnagar, etc.)
    # Common Indian cities and locations
    cities = ['mumbai', 'delhi', 'bhavnagar', 'bangalore', 'chennai', 'kolkata', 
              'pune', 'ahmedabad', 'hyderabad', 'surat', 'jaipur', 'lucknow']
    
    # Find location by looking for city names
    for city in cities:
        if city in text.lower():
            # Extract the city name as it appears in the text
            city_match = re.search(r'\b(' + re.escape(city) + r')\b', text, re.IGNORECASE)
            if city_match:
                result['location'] = city_match.group(1).title()  # Capitalize properly
                break
    
    # If no location found, check for location at the end or in parentheses
    if not result['location']:
        # Check for location at the end
        end_words = text.split()[-3:]
        for word in end_words:
            word_clean = word.strip('(),-').lower()
            if word_clean in cities:
                result['location'] = word.strip('(),-').title()
                break
    
    # Clean the title by removing experience and location information
    # Use normalized text for cleaning
    normalized_text = text.replace('–', '-').replace('—', '-')
    title = normalized_text.strip()
    
    # Remove experience if found
    if result['experience']:
        # Handle different formats like "2-4 years", "2–4 years", etc.
        exp_pattern_compiled = re.compile(result['experience'] + r'\s*(?:years?|yrs?|exp|experience)', re.IGNORECASE)
        title = exp_pattern_compiled.sub('', title).strip()
        # Also try to remove just the numbers part
        if result['experience'] in title:
            title = title.replace(result['experience'], '').strip()
    
    # Remove location if found
    if result['location']:
        title = title.replace(result['location'], '').strip()
    
    # Clean up any double spaces or punctuation
    title = re.sub(r'\s+', ' ', title).strip()
    title = re.sub(r'[,-]+\s*$', '', title)  # Remove trailing punctuation
    title = re.sub(r'^\s*[,-]+\s*', '', title)  # Remove leading punctuation
    
    # Replace normalized dashes back to the original character preference
    title = title.replace('-', '–')
    
    result['title'] = title.strip()
    
    return result


def _build_job_string(job_info: Dict[str, str]) -> str:
    """Build a formatted job string from parsed components."""
    parts = []
    
    # Add title
    title = job_info.get('title', '')
    if title:
        parts.append(title)
    
    # Add experience if available
    experience = job_info.get('experience', '')
    if experience:
        parts.append(f"- {experience} years experience")
    
    # Add location if available
    location = job_info.get('location', '')
    if location:
        parts.append(f"({location})")
    
    # Join parts
    formatted = ' '.join(parts)
    
    # Clean up any double spaces or awkward punctuation
    formatted = re.sub(r'\s+', ' ', formatted)
    formatted = re.sub(r'\s+-\s*', ' - ', formatted)
    formatted = re.sub(r'\(\s+', '(', formatted)
    formatted = re.sub(r'\s+\)', ')', formatted)
    
    return formatted.strip()


def _is_header_line(text: str) -> bool:
    """Check if text looks like a header/title line."""
    # Header lines are typically short titles or section names
    if len(text.split()) <= 3 and text.isupper():
        return True
    
    # Lines that are just titles without details
    header_words = ['jobs', 'careers', 'positions', 'openings', 'vacancies', 
                   'technologies', 'tech', 'stack', 'expertise']
    
    text_lower = text.lower()
    return any(word in text_lower for word in header_words)


def _add_careers_header(text: str) -> str:
    """Add careers header with emoji if not already present."""
    if not text or not text.strip():
        return text
    
    # Check if already starts with a header
    first_line = text.strip().split('\n')[0].strip()
    if _is_header_line(first_line):
        return text
    
    # Add careers header
    header = "💼 Current Job Openings"
    return f"{header}\n\n{text}"


def _add_technologies_header(text: str) -> str:
    """Add technologies header with emoji if not already present."""
    if not text or not text.strip():
        return text
    
    # Check if already starts with a header
    first_line = text.strip().split('\n')[0].strip()
    if _is_header_line(first_line):
        return text
    
    # Add technologies header
    header = "💻 Our Technologies & Expertise"
    return f"{header}\n\n{text}"


def answer_for_text(wa_id: str, text: str, tenant_id=None) -> str | None:
    """Answer text for a typed query, via the rules tier of intent matching.

    Deliberately rules-only (exact examples + word-boundary keywords): this
    runs in front of the LLM pipeline, so it must stay cheap and
    deterministic. An utterance that does not clearly name a panel falls
    through to the normal FAQ/KB path.
    """
    if not (text or "").strip():
        return None
    profile = _profile(tenant_id, wa_id)
    if profile is None:
        return None
    try:
        from shared.tenancy.intent_match import match_by_rules

        candidates = _answered_intents(profile)
        if not candidates:
            return None
        matched = match_by_rules(text, candidates)
        if not matched:
            return None
        intent_name, score = matched
        for intent in candidates:
            if intent.name == intent_name:
                return intent.answer.strip()
    except Exception as exc:
        logger.debug("intent_answers: text match failed (%s)", exc)
    return None
