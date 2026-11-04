import re
from typing import List, Dict, Any, Optional

def parse_questions_from_text(raw_text: str) -> List[Dict[str, Any]]:
    """
    Format parse karta hai jaise:
    Q1. Question text here?
    A) Option 1
    B) Option 2
    C) Option 3
    D) Option 4
    Ans: C ya Answer: 3
    Exp: Explanation text (optional)
    """
    # Double newlines se blocks me split karein
    blocks = re.split(r'\n\s*\n', raw_text.strip())
    questions = []

    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 3:
            continue

        q_text = ""
        options = []
        correct_idx = -1
        explanation = ""

        # Option prefix patterns: A), B., 1), (A) etc.
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
                # Agar options shuru nahi huye hain toh question text hai
                if not options:
                    clean_line = re.sub(r'^(?:[Qq](?:uestion)?\s*\d*[\.\:]?|\d+[\.\)])\s*', '', line)
                    if q_text:
                        q_text += " " + clean_line
                    else:
                        q_text = clean_line

        # Agar options mile aur correct_idx valid hai
        if q_text and len(options) >= 2 and 0 <= correct_idx < len(options):
            questions.append({
                "question": q_text[:300],  # Telegram Poll question limit
                "options": [opt[:100] for opt in options[:10]],  # Telegram option limit
                "correct_option_index": correct_idx,
                "explanation": explanation[:200] if explanation else ""
            })

    return questions
