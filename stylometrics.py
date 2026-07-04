import re
import statistics


def get_stylometric_signal(text):
    """
    Computes structural/statistical properties of the text and combines them
    into a single 0-1 score representing likelihood of AI authorship.
    Returns 0.5 (maximally uncertain) if the text is too short.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s for s in sentences if s.strip()]

    words = re.findall(r"\b[a-zA-Z']+\b", text.lower())

    if len(sentences) < 2 or len(words) < 10:
        return 0.5

    sentence_lengths = [len(re.findall(r"\b[a-zA-Z']+\b", s)) for s in sentences]
    if len(sentence_lengths) >= 2:
        length_stdev = statistics.stdev(sentence_lengths)
    else:
        length_stdev = 0

    variance_score = max(0.0, min(1.0, 1 - (length_stdev / 8)))

    unique_words = set(words)
    ttr = len(unique_words) / len(words)
    ttr_score = max(0.0, min(1.0, 1 - ttr))

    punctuation_chars = re.findall(r"[.,;:!?\"'()\-]", text)
    punct_density = len(punctuation_chars) / max(1, len(text))
    punct_score = max(0.0, min(1.0, punct_density / 0.08))

    style_score = (variance_score + ttr_score + punct_score) / 3

    return round(style_score, 4)


def compute_confidence(llm_score, style_score):
    """
    Weighted average: LLM signal weighted 0.6, stylometric signal weighted 0.4.
    """
    confidence = (0.6 * llm_score) + (0.4 * style_score)
    return round(confidence, 4)


def get_label(confidence):
    """
    Maps confidence to a label using the thresholds from planning.md:
    >=0.75 likely_ai, <=0.35 likely_human, else uncertain.
    """
    if confidence >= 0.75:
        return "likely_ai"
    elif confidence <= 0.35:
        return "likely_human"
    else:
        return "uncertain"


if __name__ == "__main__":
    test_inputs = {
        "clearly_ai": (
            "Artificial intelligence represents a transformative paradigm shift in modern society. "
            "It is important to note that while the benefits of AI are numerous, it is equally "
            "essential to consider the ethical implications. Furthermore, stakeholders across "
            "various sectors must collaborate to ensure responsible deployment."
        ),
        "clearly_human": (
            "ok so i finally tried that new ramen place downtown and honestly? "
            "underwhelming. the broth was fine but they put WAY too much sodium in it and "
            "i was thirsty for like three hours after. my friend got the spicy version and "
            "said it was better. probably won't go back unless someone drags me there"
        ),
        "borderline_formal_human": (
            "The relationship between monetary policy and asset price inflation has been "
            "extensively studied in the literature. Central banks face a fundamental tension "
            "between their mandate for price stability and the unintended consequences of "
            "prolonged low interest rates on equity and real estate valuations."
        ),
        "borderline_edited_ai": (
            "I've been thinking a lot about remote work lately. There are genuine tradeoffs - "
            "flexibility and no commute on one side, isolation and blurred work-life boundaries "
            "on the other. Studies show productivity varies widely by individual and role type."
        ),
    }

    for label, text in test_inputs.items():
        style_score = get_stylometric_signal(text)
        print(f"{label}: stylometric_score = {style_score}")