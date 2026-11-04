import re
from typing import List, Dict, Any

CHECKMARK_PATTERNS = ["✅", "✔️", "✔", "☑️", "☑", "(sahi)", "(correct)", "[correct]", "*"]
EXPLANATION_PREFIXES = ["ex:-", "ex:", "ex-", "ex.-", "exp:-", "exp:", "exp-", "exp.-", "explanation:", "explanation-", "vyakhya:", "व्याख्या:", "व्याख्या:-", "व्याख्या-"]

def is_explanation_line(line: str) -> bool:
    """Checks if a line is an explanation/detail, even if prefixed with an option letter like E) or number"""
    l = line.lower().strip()
    # Strip any leading option label like E), (E), 5., etc.
    l_clean = re.sub(r'^(?:[a-z0-9][\.\)]|\([a-z0-9]\))\s*', '', l).strip()
    return any(l.startswith(p) or l_clean.startswith(p) for p in EXPLANATION_PREFIXES)

def extract_explanation_text(line: str) -> str:
    """Extracts raw explanation text without option prefix or Ex:- label"""
    cleaned = re.sub(r'^(?:[a-z0-9][\.\)]|\([a-z0-9]\))\s*', '', line.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'^(?:ex(?:p(?:lanation)?)?|vyakhya|व्याख्या)\s*[:=\.\-]+\s*', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def clean_option_text(text: str) -> str:
    """Removes leading numbering like 1., A), (B), E) and trailing checkmarks"""
    t = text.strip()
    # Remove checkmark symbols
    for cm in CHECKMARK_PATTERNS:
        t = t.replace(cm, "")
    # Remove leading option prefix: A), 1), (A), A., E), 5., etc.
    t = re.sub(r'^(?:[A-Za-z0-9][\.\)]|\([A-Za-z0-9]\))\s*', '', t)
    return t.strip()

def parse_questions_from_text(raw_text: str) -> List[Dict[str, Any]]:
    """
    Parses questions in various Telegram formats:
    Format 1 (Tick / Checkmark format):
        Question here?
        Option 1
        Option 2
        Option 3 ✅
        Option 4
        Ex:- Explanation text...

    Format 2 (Standard Q/A format):
        Q1. Question?
        A) Option 1
        B) Option 2
        C) Option 3
        D) Option 4
        Ans: C
        Exp: Explanation...
    """
    # Normalize unicode spaces & line endings
    text = raw_text.replace('\u00a0', ' ').replace('\r\n', '\n').replace('\r', '\n')
    # Split by one or more blank lines
    blocks = re.split(r'\n\s*\n+', text.strip())
    questions = []

    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 3:
            continue

        q_text = ""
        options = []
        correct_idx = -1
        explanation = ""

        # Check if any line has a checkmark (Format 1)
        has_checkmark = any(any(cm in line for cm in CHECKMARK_PATTERNS) for line in lines[1:])

        if has_checkmark:
            # First line is Question
            q_text = re.sub(r'^(?:[Qq](?:uestion)?\s*\d*[\.\:]?|\d+[\.\)])\s*', '', lines[0]).strip()
            
            # Remaining lines are options or explanation
            for line in lines[1:]:
                # Check if this line is an explanation (Ex:-, Exp:, E) Ex:-, etc.)
                if is_explanation_line(line):
                    explanation = extract_explanation_text(line)
                    continue
                
                is_correct = any(cm in line for cm in CHECKMARK_PATTERNS)
                cleaned = clean_option_text(line)
                if cleaned:
                    if is_correct:
                        correct_idx = len(options)
                    options.append(cleaned)

        else:
            # Format 2: Regex based parsing for Q/A/B/C/D / Ans: ...
            opt_pattern = re.compile(r'^(?:[A-Za-z0-9][\.\)]|\([A-Za-z0-9]\))\s*(.+)$')
            ans_pattern = re.compile(r'^(?:ans(?:wer)?|sahi\s*uttar|uttar)\s*[:=\-]?\s*([A-Za-z0-9])', re.IGNORECASE)

            for line in lines:
                if is_explanation_line(line):
                    explanation = extract_explanation_text(line)
                    continue

                ans_match = ans_pattern.match(line)
                opt_match = opt_pattern.match(line)

                if ans_match:
                    ans_char = ans_match.group(1).upper()
                    if ans_char in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']:
                        correct_idx = ord(ans_char) - ord('A')
                    elif ans_char.isdigit():
                        correct_idx = int(ans_char) - 1
                elif opt_match:
                    options.append(opt_match.group(1).strip())
                else:
                    if not options:
                        clean_line = re.sub(r'^(?:[Qq](?:uestion)?\s*\d*[\.\:]?|\d+[\.\)])\s*', '', line).strip()
                        if q_text:
                            q_text += " " + clean_line
                        else:
                            q_text = clean_line

        # Validation
        if q_text and len(options) >= 2 and 0 <= correct_idx < len(options):
            questions.append({
                "question": q_text[:300],
                "options": [opt[:100] for opt in options[:10]],
                "correct_option_index": correct_idx,
                "explanation": explanation[:200] if explanation else ""
            })

    return questions
