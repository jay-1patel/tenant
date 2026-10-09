"""
🎨 Advanced Content Formatters for Specific Content Types

This module provides specialized formatting for different types of content:
- Career listings
- Technology stacks
- Product catalogs
- Service descriptions

Each formatter knows how to best structure the content for WhatsApp.
"""

import re
from typing import List, Dict, Optional
from services.response_formatters import WhatsAppFormatter, MessageType


def format_careers_content(career_text: str, company_name: str = "") -> str:
    """
    Format career listings with professional structure.
    
    Handles various formats:
    - Comma-separated job listings
    - Newline-separated entries
    - Mixed format content
    - Raw text with job details
    
    Example input:
    "Sales Executive 2-4 years Mumbai,BDM Executive Sales 2-5 years Mumbai"
    
    Example output:
    "💼 Current Job Openings
    
    • Sales Executive - 2-4 years experience (Mumbai)
    • BDM Executive Sales - 2-5 years experience (Mumbai)"
    """
    if not career_text or not career_text.strip():
        return career_text or ""
    
    try:
        formatter = WhatsAppFormatter()
        
        # Step 1: Normalize input
        cleaned_text = career_text.strip()
        
        # Step 2: Handle comma-separated listings
        if ',' in cleaned_text and '\n' not in cleaned_text:
            items = [item.strip() for item in cleaned_text.split(',')]
        else:
            items = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
        
        # Step 3: Process each job listing
        formatted_jobs = []
        for job in items:
            if job:  # Skip empty entries
                formatted_job = _format_single_job(job)
                formatted_jobs.append(formatted_job)
        
        # Step 4: Build final output
        if formatted_jobs:
            result = "💼 Current Job Openings\n\n" + "\n".join(formatted_jobs)
        else:
            result = cleaned_text
        
        # Step 5: Apply enhanced formatting
        result = formatter.format(result, MessageType.FAQ_ANSWER)
        
        # Step 6: Add company branding if available
        if company_name:
            result = result.replace("Current Job Openings", f"Job Openings at {company_name}")
        
        return result
        
    except Exception as e:
        # Fallback to basic formatting
        return _basic_careers_format(career_text)


def _format_single_job(job_text: str) -> str:
    """Format a single job description."""
    job_text = job_text.strip()
    if not job_text:
        return ""
    
    # Handle different job text formats
    job = _parse_job_text(job_text)
    
    # Build formatted job string
    parts = []
    
    if job.get('title'):
        parts.append(job['title'])
    
    if job.get('experience'):
        experience_text = _format_experience(job['experience'])
        if parts:
            parts[-1] += f" - {experience_text}"
        else:
            parts.append(experience_text)
    
    if job.get('location'):
        if parts:
            # Try to append location to last part
            if '(' in job_text or '[' in job_text:
                # Already has location formatting
                pass
            else:
                parts[-1] += f" ({job['location']})"
        else:
            parts.append(f"Location: {job['location']}")
    
    # Join all parts with appropriate separators
    formatted_job = " ".join(parts)
    
    # Add bullet point
    if not formatted_job.startswith('•'):
        formatted_job = f"• {formatted_job}"
    
    return formatted_job


def _parse_job_text(text: str) -> Dict[str, str]:
    """Parse job text into components using AI-like pattern matching."""
    result = {'title': '', 'experience': '', 'location': ''}
    
    # Patterns for different job components
    patterns = [
        # Experience patterns
        (r'([0-9]+[+-]?[0-9]*\s*(?:yrs?|years|year|exp|experience))', 'experience'),
        (r'((?:freshers?|entry level|senior|mid level|jr\.|sr\.))', 'experience'),
        
        # Location patterns  
        (r'((?:in|at|-|,)\s*[A-Z][a-zA-Z\s]+(?:,\s*[A-Z][a-zA-Z\s]+)*)', 'location'),
        (r'(\([A-Z][a-zA-Z\s]+\))', 'location'),
        (r'(\[[A-Z][a-zA-Z\s]+\])', 'location'),
    ]
    
    for pattern, field in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            # Clean up location parentheses/brackets
            value = value.replace('(', '').replace(')', '').replace('[', '').replace(']', '')
            result[field] = value
    
    # Extract title by removing matched parts from text
    remaining_text = text
    for field in ['experience', 'location']:
        if result[field]:
            remaining_text = remaining_text.replace(result[field], '')
    
    result['title'] = remaining_text.strip()
    
    return result


def _format_experience(exp_text: str) -> str:
    """Format experience text consistently."""
    exp_text = exp_text.strip()
    
    # Map common terms
    replacements = {
        'fresher': 'Fresher',
        'entry level': 'Entry Level', 
        'mid level': 'Mid-Level',
        'senior': 'Senior',
        'jr.': 'Junior',
        'sr.': 'Senior',
        'yrs': 'years',
        'yr': 'year',
        'exp': 'experience',
    }
    
    for old, new in replacements.items():
        exp_text = exp_text.replace(old, new)
    
    # Capitalize first letter
    if exp_text:
        exp_text = exp_text[0].upper() + exp_text[1:] if exp_text else exp_text
    
    return exp_text


def _basic_careers_format(text: str) -> str:
    """Fallback basic formatting for careers."""
    if not text:
        return text
    
    # Replace commas with newlines and add bullets
    text = re.sub(r',\s+', '\n', text)
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped:
            if not stripped.startswith('•'):
                stripped = f"• {stripped}"
            formatted_lines.append(stripped)
    
    result = '\n'.join(formatted_lines)
    
    # Add header
    if result and not result.startswith('💼'):
        result = "💼 Current Openings\n\n" + result
    
    return result


def format_technologies_content(tech_text: str, company_name: str = "") -> str:
    """
    Format technology stack content with proper structure.
    
    Handles various formats:
    - Comma-separated tech lists: "Python, Django, React"
    - Newline-separated items
    - Mixed with descriptions
    - Raw text paragraphs
    
    Example output:
    "💻 Technologies & Expertise
    
    • **Backend**: Python, Django, Flask, Node.js
    • **Frontend**: React, Vue.js, HTML5, CSS3
    • **Databases**: PostgreSQL, MySQL, MongoDB
    • **Cloud**: AWS, Azure, Google Cloud"
    """
    if not tech_text or not tech_text.strip():
        return tech_text or ""
    
    try:
        formatter = WhatsAppFormatter()
        
        # Step 1: Smart parsing based on content structure
        if _has_categories(tech_text):
            # Already has category structure
            result = _enhance_category_structure(tech_text)
        elif ',' in tech_text and '\n' not in tech_text:
            # Comma-separated list
            result = _format_comma_tech_list(tech_text)
        else:
            # Regular paragraph or newline-separated
            result = _format_regular_tech_list(tech_text)
        
        # Step 2: Add header
        result = _add_tech_header(result, company_name)
        
        # Step 3: Apply enhanced formatting
        result = formatter.format(result, MessageType.FAQ_ANSWER)
        
        return result
        
    except Exception as e:
        return _basic_tech_format(tech_text)


def _has_categories(text: str) -> bool:
    """Check if text has category structure like 'Backend: Python, Django'."""
    category_patterns = [
        r'\b(backend|frontend|database|cloud|devops|mobile|web|data|ai|ml)\b:*',
        r'\b(technologies?|tech stack|stack|expertise)\b:*',
        r'[A-Z][a-z]+\s*:',  # Any word followed by colon
    ]
    
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in category_patterns)


def _enhance_category_structure(text: str) -> str:
    """Enhance existing category structure."""
    lines = text.split('\n')
    enhanced_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped:
            # Check for category patterns and format them
            if ':' in stripped:
                category, items = stripped.split(':', 1)
                category = category.strip()
                items = items.strip()
                
                # Clean items and add bullet separator
                if items:
                    formatted_items = items
                    # If multiple items separated by commas, format as list
                    if ',' in items:
                        tech_items = [item.strip() for item in items.split(',')]
                        formatted_items = ", ".join(tech_items)
                    
                    enhanced_lines.append(f"• **{category}**: {formatted_items}")
                else:
                    enhanced_lines.append(f"• **{category}**")
            else:
                # Regular line - add bullet if not present
                if not stripped.startswith('•'):
                    stripped = f"• {stripped}"
                enhanced_lines.append(stripped)
        else:
            enhanced_lines.append('')
    
    return '\n'.join(enhanced_lines)


def _format_comma_tech_list(text: str) -> str:
    """Format comma-separated technology list."""
    # Split by commas and create bullets
    items = [item.strip() for item in text.split(',')]
    
    # Group related technologies
    grouped = _group_technologies(items)
    
    formatted_lines = []
    for category, techs in grouped.items():
        if techs:
            tech_str = ", ".join(techs)
            formatted_lines.append(f"• **{category}**: {tech_str}")
    
    return '\n'.join(formatted_lines)


def _format_regular_tech_list(text: str) -> str:
    """Format regular tech list."""
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped:
            if not stripped.startswith('•') and ':' not in stripped:
                stripped = f"• {stripped}"
            formatted_lines.append(stripped)
        else:
            formatted_lines.append('')
    
    return '\n'.join(formatted_lines)


def _group_technologies(tech_list: List[str]) -> Dict[str, List[str]]:
    """Group technologies by category."""
    # Define technology categories and their keywords
    categories = {
        "Backend": ['python', 'java', 'node', 'django', 'flask', 'spring', 'ruby', 'go', 'rust'],
        "Frontend": ['react', 'vue', 'angular', 'javascript', 'typescript', 'html', 'css'],
        "Mobile": ['android', 'ios', 'kotlin', 'swift', 'flutter', 'react native'],
        "Database": ['mysql', 'postgresql', 'mongodb', 'redis', 'sqlite', 'oracle'],
        "Cloud": ['aws', 'azure', 'gcp', 'google cloud', 'ec2', 'lambda', 'docker'],
        "DevOps": ['docker', 'kubernetes', 'ci/cd', 'jenkins', 'terraform'],
        "AI/ML": ['ai', 'ml', 'machine learning', 'tensorflow', 'pytorch', 'nlp'],
        "Big Data": ['hadoop', 'spark', 'hive', 'kafka', 'data lake'],
        "Security": ['auth', 'security', 'oauth', 'jwt', 'encryption'],
    }
    
    # Categorize each technology
    categorized = {category: [] for category in categories.keys()}
    uncategorized = []
    
    for tech in tech_list:
        tech_lower = tech.lower()
        categorized_flag = False
        
        for category, keywords in categories.items():
            for keyword in keywords:
                if keyword in tech_lower:
                    categorized[category].append(tech)
                    categorized_flag = True
                    break
        
        if not categorized_flag:
            uncategorized.append(tech)
    
    # Add uncategorized to a general group
    if uncategorized:
        categorized["General"] = uncategorized
    
    return categorized


def _add_tech_header(text: str, company_name: str = "") -> str:
    """Add technologies header."""
    if not text:
        return text
    
    header_text = "💻 Technologies & Expertise"
    if company_name:
        header_text = f"💻 {company_name}'s Technologies & Expertise"
    
    # Check if header already exists
    if text.startswith('💻'):
        return text
    
    return f"{header_text}\n\n{text}"


def _basic_tech_format(text: str) -> str:
    """Fallback basic formatting for technologies."""
    if not text:
        return text
    
    # Replace commas with newlines and add bullets
    text = re.sub(r',\s+', '\n', text)
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped:
            if not stripped.startswith('•'):
                stripped = f"• {stripped}"
            formatted_lines.append(stripped)
    
    result = '\n'.join(formatted_lines)
    
    # Add header
    if result and not result.startswith('💻'):
        result = "💻 Our Technologies\n\n" + result
    
    return result


def format_product_listing(products: List[Dict], title: str = "Our Products") -> str:
    """Format a list of products with proper structure."""
    if not products:
        return "No products available."
    
    formatted_items = []
    
    for product in products:
        name = product.get('name', 'Unnamed Product')
        price = product.get('price', 'Price on request')
        category = product.get('category', '')
        description = product.get('description', '')
        
        # Format each product
        product_text = f"**{name}**"
        if category:
            product_text += f" ({category})"
        if price and price != 'Price on request':
            product_text += f" - ₹{price}"
        if description:
            product_text += f": {description}"
        
        formatted_items.append(f"• {product_text}")
    
    result = "\n".join(formatted_items)
    
    # Add title
    result = f"📦 {title}\n\n{result}"
    
    # Apply enhanced formatting
    try:
        formatter = WhatsAppFormatter()
        result = formatter.format(result, MessageType.PRODUCT_INFO)
    except:
        pass
    
    return result


# 🎯 Convenience Functions

def smart_format_content(content: str, content_type: str, **kwargs) -> str:
    """
    Smart formatting based on content type.
    
    Args:
        content: The text content to format
        content_type: Type of content ('careers', 'technologies', 'products', etc.)
        **kwargs: Additional formatting options
        
    Returns:
        Formatted content
    """
    formatters = {
        'careers': format_careers_content,
        'jobs': format_careers_content,
        'openings': format_careers_content,
        'technologies': format_technologies_content,
        'tech': format_technologies_content,
        'technology': format_technologies_content,
        'products': lambda text: format_product_listing(kwargs.get('items', []), kwargs.get('title', 'Products')),
    }
    
    formatter = formatters.get(content_type.lower(), None)
    
    if formatter:
        return formatter(content, **kwargs)
    else:
        # Default formatting
        try:
            formatter = WhatsAppFormatter()
            return formatter.format(content, MessageType.FAQ_ANSWER)
        except:
            return content


# 🧪 Test Function
if __name__ == "__main__":
    print("=== CAREERS FORMATTING DEMO ===")
    
    careers_input = """Sales Executive Sales 2-4 years Mumbai
BDM Executive Sales 2-5 years Mumbai  
Back Office Executive Sales 0-2 years Bhavnagar
AEO/SEO Executive Sales 2-4 years Delhi"""
    
    print("BEFORE:")
    print(careers_input)
    print("\nAFTER:")
    print(format_careers_content(careers_input, "TechCorp"))
    
    print("\n=== TECHNOLOGIES FORMATTING DEMO ===")
    
    tech_input = "Python, Django, Flask, React, Vue.js, MySQL, PostgreSQL, AWS, Docker, Kubernetes"
    
    print("BEFORE:")
    print(tech_input)
    print("\nAFTER:")
    print(format_technologies_content(tech_input, "TechCorp"))
    
    print("\n=== COMMA-SEPARATED CAREERS ===")
    
    careers_comma = "Sales Executive 2-4 years Mumbai, BDM Executive Sales 2-5 years Mumbai, Back Office Executive 0-2 years"
    
    print("BEFORE:")
    print(careers_comma)
    print("\nAFTER:")
    print(format_careers_content(careers_comma))