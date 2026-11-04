import re
from typing import List, Dict, Any

CHECKMARK_PATTERNS = ["✅", "✔️", "✔", "☑️", "☑", "(sahi)", "(correct)", "[correct]", "*"]

def clean_option_text(text: str) -> str:
    """Removes leading numbering like 1., A), (B) and trailing checkmarks"""
    t = text.strip()
    # Remove checkmark symbols
    for cm in CHECKMARK_PATTERNS:
        t = t.replace(cm, "")
    # Remove leading option prefix: A), 1), (A), A.
    t = re.sub(r'^(?:[A-Da-d0-9][\.\)]|\([A-Da-d0-9]\))\s*', '', t)
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
            
            # Remaining lines are options
            for idx, line in enumerate(lines[1:]):
                is_correct = any(cm in line for cm in CHECKMARK_PATTERNS)
                cleaned = clean_option_text(line)
                if cleaned:
                    if is_correct:
                        correct_idx = len(options)
                    options.append(cleaned)

        else:
            # Format 2: Regex based parsing for Q/A/B/C/D / Ans: ...
            opt_pattern = re.compile(r'^(?:[A-Da-d0-9][\.\)]|\([A-Da-d0-9]\))\s*(.+)$')
            ans_pattern = re.compile(r'^(?:ans(?:wer)?|sahi\s*uttar|uttar)\s*[:=\-]?\s*([A-Da-d1-9])', re.IGNORECASE)
            exp_pattern = re.compile(r'^(?:exp(?:lanation)?|vyakhya)\s*[:=\-]?\s*(.+)$', re.IGNORECASE)

            for line in lines:
                ans_match = ans_pattern.match(line)
                exp_match = exp_pattern.match(line)
                opt_match = opt_pattern.match(line)

                if ans_match:
                    ans_char = ans_match.group(1).upper()
                    if ans_char in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']:
                        correct_idx = ord(ans_char) - ord('A')
                    elif ans_char.isdigit():
                        correct_idx = int(ans_char) - 1
                elif exp_match:
                    explanation = exp_match.group(1).strip()
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
