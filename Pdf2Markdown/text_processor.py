import re

def clean_markdown_text(text):
    """
    Post-process Markdown text to fix broken sentences and extra whitespace 
    caused by PDF conversion.
    """
    # 1. Normalize horizontal spaces
    text = re.sub(r'[ 	]+', ' ', text)
    
    lines = text.splitlines()
    cleaned_blocks = []
    current_paragraph = []
    
    # Calculate rough "full line" length
    content_lines = [len(l.strip()) for l in lines if l.strip()]
    if not content_lines:
        return text
    
    max_len = max(content_lines)
    threshold = max_len * 0.7 
    
    for line in lines:
        line = line.strip()
        
        if not line:
            if current_paragraph:
                cleaned_blocks.append(" ".join(current_paragraph))
                current_paragraph = []
            continue
            
        # Refined Header/Title Detection
        is_numbered = re.match(r'^\d+(\.\d+)*[\s\.]', line)
        
        # Detect wide-spaced headers like "O P E R A T I O N A L"
        is_wide_spaced = re.match(r'^([A-Z]\s){3,}[A-Z]$', line)
        
        # Detect all-caps headers
        is_all_caps = line.isupper() and len(line) > 3
        
        is_short = len(line) < threshold
        ends_punctuation = line[-1] in '.!?:;"'
        
        # Heuristic for header
        is_header = (
            is_numbered or 
            is_wide_spaced or 
            (is_all_caps and is_short) or
            (is_short and not ends_punctuation and len(line) < threshold * 0.4)
        )
        
        if is_header:
            if current_paragraph:
                cleaned_blocks.append(" ".join(current_paragraph))
                current_paragraph = []
            
            # If wide spaced, compact it
            if is_wide_spaced:
                line = line.replace(" ", "")
                
            cleaned_blocks.append("\n" + line + "\n")
            continue
            
        # Body text processing
        current_paragraph.append(line)
        
        # Paragraph break heuristic
        if ends_punctuation and is_short:
            cleaned_blocks.append(" ".join(current_paragraph))
            current_paragraph = []
            
    # Final flush
    if current_paragraph:
        cleaned_blocks.append(" ".join(current_paragraph))
        
    # Join with double newlines
    result = "\n\n".join(cleaned_blocks)
    
    # Remove excessive newlines
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result.strip()