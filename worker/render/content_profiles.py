PROFILES = {
    "christian_egypt": {
        "style": "Photorealistic cinematic documentary photograph, vertical 9:16 composition, warm natural light, shallow depth of field, authentic modern Egypt, professional color grading.",
        "rules": "Egyptian Coptic Christian setting. Every woman and girl has visible, uncovered hair and wears a simple modern everyday outfit. Men wear modern everyday clothes. Religious symbols are limited to a cross, candles, an open Bible, church architecture and rays of light; God and Jesus are never shown as a person. Pages, signs and screens are blank, with no letters or writing anywhere.",
    },
    "kids": {
        "style": "Bright friendly 3D animated children's film style, soft rounded characters, vivid colors, gentle lighting, vertical 9:16 composition.",
        "rules": "Child-safe, cheerful and wholesome. Simple clean background, large expressive friendly faces, no scary elements, no letters or writing anywhere.",
    },
    "teens": {
        "style": "Modern lifestyle photograph, dynamic composition, natural light, authentic everyday settings, vertical 9:16 composition.",
        "rules": "Teenagers in everyday school, home and street settings, modest casual clothing, relatable and realistic, no letters or writing anywhere.",
    },
    "youth": {
        "style": "Cinematic realistic photograph, modern urban atmosphere, natural moody light, vertical 9:16 composition.",
        "rules": "Young adults in modern everyday settings, modest stylish clothing, authentic emotions, no letters or writing anywhere.",
    },
    "international": {
        "style": "Photorealistic cinematic photograph, vertical 9:16 composition, natural light, professional composition.",
        "rules": "Western international setting with diverse realistic people in everyday modern clothing, no letters or writing anywhere.",
    },
    "general": {
        "style": "Photorealistic cinematic photograph, vertical 9:16 composition, natural light, professional color grading.",
        "rules": "Realistic people and authentic environments matching the scene, no letters or writing anywhere.",
    },
}


def get_profile(name):
    key = str(name or "").strip().lower()
    return PROFILES.get(key, PROFILES["general"])
