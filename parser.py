import re
from db import add_general_question

def parse_and_save_quiz_text(raw_text: str, default_cat: str = "general") -> int:
    """
    Format:
    Q: Bharat ki rajdhani kya hai?
    A) Mumbai
    B) New Delhi
    C) Kolkata
    D) Chennai
    Ans: B
    Exp: New Delhi Bharat ki rajdhani hai.
    """
    blocks = raw_text.strip().split("\n\n")
    saved_count = 0
    
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 5:
            continue
            
        question = lines[0].replace("Q:", "").replace("Q.", "").strip()
        opt_a = lines[1].replace("A)", "").replace("A.", "").strip()
        opt_b = lines[2].replace("B)", "").replace("B.", "").strip()
        opt_c = lines[3].replace("C)", "").replace("C.", "").strip()
        opt_d = lines[4].replace("D)", "").replace("D.", "").strip()
        
        correct_id = 0
        explanation = "Great job!"
        
        for line in lines[5:]:
            if line.lower().startswith(("ans:", "ans.", "answer:")):
                ans_char = line.split(":")[-1].strip().upper()
                mapping = {"A": 0, "B": 1, "C": 2, "D": 3}
                correct_id = mapping.get(ans_char, 0)
            elif line.lower().startswith(("exp:", "explanation:")):
                explanation = line.split(":", 1)[-1].strip()
                
        add_general_question(question, opt_a, opt_b, opt_c, opt_d, correct_id, explanation, default_cat)
        saved_count += 1
        
    return saved_count
