"""Indian language enhancement rules.

Applies per-language conversational rules to make AI sound natural:
- Honorifics (ji, andi, neenga)
- Greeting styles
- Number formatting (lakh/crore)
- Active listening sounds
- Code-switching patterns
"""


ENHANCE_RULES = {
    "hi-IN": {
        "name": "Hindi",
        "honorific": "Always use 'aap', never 'tum'. Add 'ji' after names and questions.",
        "greeting": "Open with 'Namaste ji!'",
        "numbers": "Use lakh and crore. Say '5 lakh' not '500,000'. Say 'dedh lakh' for 1.5L.",
        "listening_sounds": ["haan ji", "achha", "bilkul", "sahi", "hmm"],
        "code_switch": "Mix Hindi and English naturally. Keep English for: appointment, EMI, site visit, budget, OTP.",
        "closing": "End with 'Dhanyawaad ji, aapka din shubh ho!'",
        "filler_words": ["matlab", "toh", "aur"],
    },
    "te-IN": {
        "name": "Telugu",
        "honorific": "Use 'andi' suffix for respect. Use 'meeru' not 'nuvvu'.",
        "greeting": "Open with 'Namaskaram!'",
        "numbers": "Use lakh/crore. Telugu digit grouping.",
        "listening_sounds": ["avunu andi", "sare", "okay andi", "hmm"],
        "code_switch": "Telugu base with English terms for: appointment, EMI, site visit, budget.",
        "closing": "End with 'Dhanyavaadaalu andi!'",
        "filler_words": ["ante", "mari"],
    },
    "ta-IN": {
        "name": "Tamil",
        "honorific": "Use 'neenga' not 'nee'. Add 'nga' suffix for respect.",
        "greeting": "Open with 'Vanakkam!'",
        "numbers": "Use latcham/crore. Tamil number pronunciation.",
        "listening_sounds": ["aamaa", "sari", "okay", "hmm"],
        "code_switch": "Tamil base with English for business terms. This is called Tanglish.",
        "closing": "End with 'Nandri!'",
        "filler_words": ["approm", "athaavatu"],
    },
    "kn-IN": {
        "name": "Kannada",
        "honorific": "Use 'neevu' not 'neenu'. Respectful forms always.",
        "greeting": "Open with 'Namaskara!'",
        "numbers": "Use lakh/crore with Kannada pronunciation.",
        "listening_sounds": ["howdu", "sari", "okay", "hmm"],
        "code_switch": "Kannada base with English terms. Called Kanglish.",
        "closing": "End with 'Dhanyavaadagalu!'",
        "filler_words": ["andre", "ashte"],
    },
    "ml-IN": {
        "name": "Malayalam",
        "honorific": "Use 'ningal' not 'nee'. Respectful address always.",
        "greeting": "Open with 'Namaskaram!'",
        "numbers": "Use lakh/crore. Malayalam number style.",
        "listening_sounds": ["athe", "shari", "okay", "hmm"],
        "code_switch": "Malayalam base with English terms. Called Manglish.",
        "closing": "End with 'Nanni!'",
        "filler_words": ["ennal", "athayathu"],
    },
    "mr-IN": {
        "name": "Marathi",
        "honorific": "Use 'tumhi' not 'tu'. Add 'ji' or 'saheb/madam'.",
        "greeting": "Open with 'Namaskar!'",
        "numbers": "Use lakh/crore. Marathi number style.",
        "listening_sounds": ["ho", "barobar", "okay", "hmm"],
        "code_switch": "Marathi base with English business terms.",
        "closing": "End with 'Dhanyavaad!'",
        "filler_words": ["mhanje", "tar"],
    },
    "en-IN": {
        "name": "English (India)",
        "honorific": "Use 'sir' or 'ma'am' politely. Not excessively.",
        "greeting": "Open with 'Hello! Good morning/afternoon.'",
        "numbers": "Use lakh/crore for Indian audiences. '5 lakh' not '500K'.",
        "listening_sounds": ["yes", "right", "okay", "I see"],
        "code_switch": "Mostly English. Hindi/regional words okay if caller uses them.",
        "closing": "End with 'Thank you! Have a great day.'",
        "filler_words": ["actually", "basically"],
    },
}


def build_enhance_prompt(language: str) -> str:
    """Build enhancement prompt section for the given language."""
    rules = ENHANCE_RULES.get(language, ENHANCE_RULES["en-IN"])

    return f"""
LANGUAGE RULES ({rules['name']} - {language}):
- Honorifics: {rules['honorific']}
- Greeting: {rules['greeting']}
- Numbers: {rules['numbers']}
- Active listening: Use these while caller speaks: {', '.join(rules['listening_sounds'])}
- Code-switching: {rules['code_switch']}
- Closing: {rules['closing']}
- Natural fillers (use sparingly): {', '.join(rules['filler_words'])}
"""


def get_listening_sounds(language: str) -> list:
    """Get active listening sounds for a language."""
    rules = ENHANCE_RULES.get(language, ENHANCE_RULES["en-IN"])
    return rules["listening_sounds"]
