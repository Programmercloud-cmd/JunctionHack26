"""Deterministic speech presentation; source answers and evidence are never mutated.

Only recognized metadata syntax is removed. Unrecognized prose is retained so a
formatting heuristic cannot silently erase a measurement or uncertainty qualifier.
"""
import re

from .schemas import Answer

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_CATEGORIES = {
    "coordinates": r"\b(?:coordinates?|coords?|bbox(?:es)?|bounding\s+box(?:es)?)\b",
    "ids": r"\b(?:ids?|identifiers?|globalids?|global_ids?|object_ids?|element_ids?|step(?:\s+(?:ids?|references?|numbers?))?)\b",
    "citations": r"\b(?:citations?|references?|evidence\s+(?:labels?|references?)|page[ -]region\s+references?)\b",
}
_CUES = re.compile(
    r"(?P<negative>\b(?:without|excluding|omit|skip|avoid)\b|\bno\s+need\s+(?:for|to\s+(?:include|read|show|give))\b|"
    r"\b(?:do\s+not|don't|don’t|not)\s+(?:include|read|show|give|list|say|speak|provide|return|mention|tell)\b|\bno\b|\bnot\b)"
    r"|(?P<positive>\b(?:include|read|show|give|list|say|speak|provide|return|tell|mention|what|which)\b)", re.I)
_COORD_LABEL = re.compile(r"\b(?:at\s+)?(?:normalized\s+)?(?:coordinates?|coords?|bbox(?:es)?|bounding\s+box(?:es)?)\s*(?:(?:are|is|at)\b\s*|[:=]\s*)?", re.I)
_OPAQUE = re.compile(r"(?<![\w$])(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-3][\w$]{21})(?![\w$])", re.I)
_HUMAN_WINDOW = re.compile(r"W[-_]?\d+(?:[-_]\d+)?", re.I)
_ID_LABEL = re.compile(r"\b(?:GlobalId|global_id|object[_ ]?ids?|element[_ ]?ids?|IFC\s+IDs?)\s*[:=]?\s*[`\"']?([A-Za-z0-9_$#./:-]+)[`\"']?", re.I)
_STEP = re.compile(r"\b(?:STEP(?:\s+(?:record|ID|reference|number))?|IFC\s+record)\s*(?:[:=]\s*#?|#)\d+\b", re.I)


def _requested_categories(question: str):
    positive, negative = set(), set()
    for clause in re.split(r"[.!?;\n]|\b(?:but|however)\b", question, flags=re.I):
        for category, pattern in _CATEGORIES.items():
            for match in re.finditer(pattern, clause, re.I):
                cues = list(_CUES.finditer(clause[:match.start()]))
                if cues:
                    cue = cues[-1]
                    between = clause[cue.end():match.start()]
                    for other_pattern in _CATEGORIES.values():
                        between = re.sub(other_pattern, "", between, flags=re.I)
                    # Bind the request to metadata itself, not a width question
                    # which merely identifies its target using an object ID.
                    between = re.sub(r"\b(?:any|all|the|a|an|me|us|please|just|their|its|these|those|this|that|are|is|were|was|be|of|and|or|also|along|with|exact|normalized|technical|full|object|element|global|ifc|page|region|numbers?|values?|windows?|rooms?|doors?|walls?)\b", "", between, flags=re.I)
                    if not between.strip(" ,:-"):
                        (negative if cue.lastgroup == "negative" else positive).add(category)
                elif not clause[:match.start()].strip() and "?" in question:
                    positive.add(category)
    return positive - negative


def _numeric_value_end(text: str, start: int):
    """Recognize a numeric value, never consume arbitrary parenthetical prose."""
    if start >= len(text):
        return None
    pairs = {"[": "]", "(": ")", "{": "}"}
    if text[start] in pairs:
        stack = []
        for index in range(start, len(text)):
            char = text[index]
            if char in pairs:
                stack.append(pairs[char])
            elif char in "]) }".replace(" ", ""):
                if not stack or stack.pop() != char:
                    return None
                if not stack:
                    inside = text[start:index + 1]
                    numbers = re.findall(_NUMBER, inside)
                    remainder = re.sub(_NUMBER, "", inside)
                    remainder = re.sub(r"\b(?:x|y|z|u|v|left|right|top|bottom|min|max)\b", "", remainder, flags=re.I)
                    if len(numbers) >= 2 and not re.sub(r"[\s\[\](){}:,;=\"']", "", remainder):
                        return index + 1
                    return None
        return None
    # Unbracketed numeric coordinates require commas or named axes, so ordinary
    # measurements such as '1.2 m, 1.4 m' do not match.
    numeric = re.match(rf"{_NUMBER}(?:\s*,\s*{_NUMBER})+", text[start:])
    if numeric:
        return start + numeric.end()
    named = re.match(rf"(?:[xyzuv]|left|right|top|bottom)\s*[:=]\s*{_NUMBER}(?:[\s,;]+(?:[xyzuv]|left|right|top|bottom)\s*[:=]\s*{_NUMBER})+", text[start:], re.I)
    return start + named.end() if named else None


def _annotation_context(text: str, start: int, end: int):
    """A label/value standing between delimiters is an annotation, not a noun."""
    before, after = text[:start].rstrip(), text[end:].lstrip()
    left_delimited = not before or before.endswith(tuple("([{;,:.!?"))
    right_delimited = not after or after.startswith(tuple(")]};,.:!?"))
    # '(coordinates [...]) are uncertain' still has a substantive predicate.
    after_closers = re.sub(r"^[\s\])}]+", "", after)
    predicate_after_closers = bool(re.match(r"[A-Za-z]", after_closers))
    return left_delimited and right_delimited and not predicate_after_closers


def _remove_coordinates(text: str):
    spans = []
    for label in _COORD_LABEL.finditer(text):
        end = _numeric_value_end(text, label.end())
        if end is None:
            continue
        replacement = ""
        if not _annotation_context(text, label.start(), end):
            replacement = label[0].strip().rstrip(":=").rstrip()
            if label[0].lower().startswith("at "):
                noun = "region" if "box" in label[0].lower() else "location"
                replacement = "at the indicated " + noun
            elif re.search(r"\b(?:inspect|check|review|locate|see|verify|in|within|near)\s*$", text[:label.start()], re.I):
                noun = "region" if "box" in label[0].lower() else "location"
                replacement = "the indicated " + noun
        spans.append((label.start(), end, replacement))
    for start, end, replacement in reversed(spans):
        text = text[:start] + replacement + text[end:]
    return text


def _opaque(value: str):
    if _HUMAN_WINDOW.fullmatch(value):
        return False
    return bool((_OPAQUE.fullmatch(value) and any(c.isalpha() for c in value)) or
                (len(value) >= 16 and any(c.isdigit() for c in value) and any(c in "_:-/$" for c in value)))


def _remove_ids(text: str, answer: Answer):
    known = list(answer.highlight_ids) + [ref.element_id for ref in answer.model_evidence if ref.element_id]
    collection = re.compile(r"\b(?:GlobalIds?|global_ids?|object[_ ]?ids?|element[_ ]?ids?|IFC\s+IDs?)\s*[:=]?\s*(\[[^\]]*\])", re.I)
    def identifier_collection(match):
        values = [value.strip(" \t\r\n\"'") for value in match[1][1:-1].split(",")]
        if not values or not all(_opaque(value) for value in values):
            return match[0]
        if _annotation_context(text, match.start(), match.end()):
            return ""
        return match[0][:match.start(1) - match.start()].strip(" :=")
    text = collection.sub(identifier_collection, text)
    def labelled(match):
        value = match[1].rstrip(".,;:")
        punctuation = match[1][len(value):]
        # Human-facing window marks remain meaningful even when called an ID.
        if _HUMAN_WINDOW.fullmatch(value):
            return value + punctuation
        if _opaque(value) or value in known or any(char.isdigit() for char in value):
            if _annotation_context(text, match.start(), match.end() - len(punctuation)):
                return punctuation
            label = match[0][:match.start(1) - match.start()].strip(" :=`\"'")
            return label + punctuation
        return match[0]
    text = _ID_LABEL.sub(labelled, text)
    text = _STEP.sub(lambda m: "" if _annotation_context(text, m.start(), m.end()) else re.sub(r"\s*[:=#]\s*#?\d+$", "", m[0]), text)
    def opaque_replacement(match):
        if not _opaque(match[0]):
            return match[0]
        if _annotation_context(text, match.start(), match.end()):
            return ""
        if re.search(r"\b(?:window|room|wall|door|object|element)\s*$", text[:match.start()], re.I):
            return ""
        return "the referenced object"
    for value in sorted(set(known), key=len, reverse=True):
        if _opaque(value):
            text = re.sub(r"(?<![\w$])" + re.escape(value) + r"(?![\w$])", opaque_replacement, text)
    text = _OPAQUE.sub(opaque_replacement, text)
    # An explicitly labelled class is metadata, unlike plain 'window' wording.
    text = re.sub(r"\b(?:IFC\s+class|ifc_type)\s*[:=]\s*Ifc[A-Za-z]+\b", "", text)
    return text


def _remove_citations(text: str, answer: Answer):
    # Bracketed labels and explicit :/# syntax are metadata. Bare [1] may be
    # a window option, and 'references 2 windows' is ordinary factual prose.
    patterns = [
        r"(?<=[\[(])(?:citations?|references?|refs?|evidence)\s*[:#]?\s*\d+(?:\s*[,;]\s*\d+)*\b",
        r"\b(?:citations?|references?|refs?|evidence)\s*[:#]\s*\d+(?:\s*[,;]\s*\d+)*\b",
        r"\bcitation\s+\d+\b",
        r"\b(?:citations?|references?|refs?|evidence)\s*[:#]?\s*\[\s*\d+(?:\s*,\s*\d+)*\s*\]",
    ]
    def reference(match):
        if _annotation_context(text, match.start(), match.end()):
            return ""
        return re.match(r"[A-Za-z]+", match[0])[0]
    for reference_pattern in patterns:
        text = re.sub(reference_pattern, reference, text, flags=re.I)
    pattern = re.compile(r"\b(?:(?:source|citation|reference)\s*:\s*)?(?:page|p\.)\s*\d+\s*[,;:]?\s+region\s*[:#]?\s*\d+\b", re.I)
    def page_region(match):
        before, after = text[:match.start()].rstrip(), text[match.end():]
        metadata_context = before.endswith(("(", "[")) or bool(re.match(r"(?:source|citation|reference)\s*:", match[0], re.I))
        tail = re.sub(r"^[\s\])}]+", "", after)
        substantive_tail = bool(re.match(r"[A-Za-z]", tail))
        return "" if metadata_context and not substantive_tail else match[0]
    text = pattern.sub(page_region, text)
    standalone = re.compile(r"\b(?:citation|reference|evidence|source)\s*:\s*(?:page|p\.)\s*\d+\b", re.I)
    return standalone.sub(lambda m: "" if _annotation_context(text, m.start(), m.end()) else m[0], text)


def _tidy(text: str, *, keep_reference_urls=False):
    text = re.sub(r"(?m)^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = text.replace("`", "")
    text = re.sub(r"\[([^\]]+)\]\(([^\s)]+)\)", lambda m: f"{m[1]} ({m[2]})" if keep_reference_urls else m[1], text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"[\[({]\s*[,;:]*\s*[\])}]", "", text)
        text = re.sub(r"([\[({])\s*[,;:]\s*", r"\1", text)
        text = re.sub(r"\s*[,;:]\s*([\])}])", r"\1", text)
    lines = [line.strip(" \t,;:") for line in text.splitlines() if line.strip(" \t,;:")]
    text = " ".join(line if line.endswith(tuple(".!?;:")) else line + "." for line in lines)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,;:!?]|\.(?!\d))", r"\1", text)
    text = re.sub(r"[,;:]\s*([,.;:!?])", r"\1", text)
    text = re.sub(r"(?<![\d.])\.(?:\s*\.)+(?![\d.])", ".", text)
    return text.strip(" ,;:")


def prepare_spoken_answer(answer: Answer, original_question: str, *, include_technical_details: bool = False) -> str:
    """Prepare speech without new inference, sentence omission, or answer mutation."""
    requested = set(_CATEGORIES) if include_technical_details else _requested_categories(original_question)
    def format_text(text):
        if "citations" not in requested:
            text = _remove_citations(text, answer)
        if "coordinates" not in requested:
            text = _remove_coordinates(text)
        if "ids" not in requested:
            text = _remove_ids(text, answer)
        return _tidy(text, keep_reference_urls="citations" in requested)

    text = format_text(answer.answer)
    if not text or not any(character.isalnum() for character in text):
        text = "Technical details are available in the written answer"
    parts = []
    if answer.status == "insufficient":
        parts.append("The inspected source does not provide enough information.")
    elif answer.status == "unclear":
        parts.append("The answer remains unclear from the inspected source.")
    parts.append(text if text.endswith(tuple(".!?")) else text + ".")
    # Never substring-deduplicate these: a main-text mention of a height does not
    # resolve a separate missing-height qualification. Keep every nonempty item.
    missing = [format_text(item).rstrip(".!? ") or "Technical details" for item in answer.missing_information if item.strip()]
    if missing:
        parts.append("Missing or unresolved: " + "; ".join(missing) + ".")
    if answer.next_action.strip():
        action = format_text(answer.next_action) or "See the technical details in the written answer"
        parts.append("Next step: " + action + ("" if action.endswith(tuple(".!?")) else "."))
    return " ".join(parts)


def with_spoken_answers(answer: Answer, question: str) -> Answer:
    if answer.status == "clarification":
        return answer
    try:
        spoken = prepare_spoken_answer(answer, question)
        detailed = prepare_spoken_answer(answer, question, include_technical_details=True)
    except Exception:
        # Speech is optional. Keep the grounded answer if formatting fails.
        return answer
    return answer.model_copy(update={
        "spoken_answer": spoken,
        "spoken_answer_with_details": detailed,
    })
