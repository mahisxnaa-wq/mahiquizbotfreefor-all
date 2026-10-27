# Quiz Questions Collection
# format:
# {
#     "question": "Sawaal yahan likhein",
#     "options": ["Option A", "Option B", "Option C", "Option D"],
#     "correct_id": 0, # Sahi answer ka index (0, 1, 2, ya 3)
#     "explanation": "Answer ka reason/explanation",
#     "category": "science / gk / computer / history"
# }

QUIZ_DATA = [
    # Computer & Tech
    {
        "question": "CPU ka full form kya hai?",
        "options": ["Central Process Unit", "Central Processing Unit", "Computer Personal Unit", "Control Processing Unit"],
        "correct_id": 1,
        "explanation": "CPU stands for Central Processing Unit, ise computer ka dimag bhi kehte hain.",
        "category": "computer"
    },
    {
        "question": "Python programming language kisne develop ki thi?",
        "options": ["Guido van Rossum", "Dennis Ritchie", "James Gosling", "Bjarne Stroustrup"],
        "correct_id": 0,
        "explanation": "Python ko Guido van Rossum ne 1991 me banaya tha.",
        "category": "computer"
    },
    {
        "question": "RAM ka nature kaisa hota hai?",
        "options": ["Permanent", "Volatile (Temporary)", "Read Only", "Non-Volatile"],
        "correct_id": 1,
        "explanation": "RAM volatile memory hoti hai, power band hone par data erase ho jata hai.",
        "category": "computer"
    },
    
    # Science
    {
        "question": "Pani (Water) ka chemical formula kya hai?",
        "options": ["CO2", "H2O", "NaCl", "O2"],
        "correct_id": 1,
        "explanation": "Water do Hydrogen aur ek Oxygen atom se banta hai (H2O).",
        "category": "science"
    },
    {
        "question": "Manav sharir ki sabse lambi haddi (longest bone) konsi hai?",
        "options": ["Tibia", "Femur (Thigh bone)", "Humerus", "Fibula"],
        "correct_id": 1,
        "explanation": "Femur (jaangh ki haddi) insani sharir ki sabse badi aur majboot haddi hoti hai.",
        "category": "science"
    },
    {
        "question": "Suraj ki roshni se hume konsa vitamin milta hai?",
        "options": ["Vitamin A", "Vitamin B", "Vitamin C", "Vitamin D"],
        "correct_id": 3,
        "explanation": "Sunlight ki madad se hamari skin Vitamin D produce karti hai.",
        "category": "science"
    },
    
    # General Knowledge & History
    {
        "question": "Bharat ka rashtriya pashu (National Animal) konsa hai?",
        "options": ["Sher (Lion)", "Baagh (Tiger)", "Hathi (Elephant)", "Cheetah"],
        "correct_id": 1,
        "explanation": "Royal Bengal Tiger Bharat ka National Animal hai.",
        "category": "gk"
    },
    {
        "question": "ISRO ka mukhyalaya (Headquarters) kahan sthit hai?",
        "options": ["New Delhi", "Mumbai", "Bengaluru", "Hyderabad"],
        "correct_id": 2,
        "explanation": "ISRO ka head office Bengaluru, Karnataka me hai.",
        "category": "gk"
    },
    {
        "question": "Constitution of India kis tarikh ko lagu (enacted) hua tha?",
        "options": ["15 August 1947", "26 January 1950", "26 November 1949", "2 October 1950"],
        "correct_id": 1,
        "explanation": "26 January 1950 ko Republic Day manaya jata hai kyunki is din samvidhan lagu hua tha.",
        "category": "history"
    },
    {
        "question": "Duniya ka sabse uncha parvat (Highest Mountain) konsa hai?",
        "options": ["K2", "Mount Everest", "Kanchenjunga", "Makalu"],
        "correct_id": 1,
        "explanation": "Mount Everest (8,848.86 meters) sabse uncha mountain peak hai.",
        "category": "gk"
    }
]
