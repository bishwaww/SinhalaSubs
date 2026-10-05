"""Find and repair wrong-script letters in Sinhala text.

Speech models sometimes write letters from related Indian scripts
(Malayalam, Tamil, Devanagari, Telugu) inside Sinhala words, because
they sound the same. Each of those scripts has the same basic sounds,
so we can map a letter to the Sinhala letter with the same sound.
"""

from __future__ import annotations

import re

# The same sounds written in each script, in the same order.
# Consonants: ka kha ga gha nga ca cha ja jha nya tta ttha dda ddha nna
#             ta tha da dha na pa pha ba bha ma ya ra la va sha ssa sa ha lla
_CONSONANTS = {
    "sinhala":    "කඛගඝඞචඡජඣඤටඨඩඪණතථදධනපඵබභමයරලවශෂසහළ",
    "devanagari": "कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहळ",
    "malayalam":  "കഖഗഘങചഛജഝഞടഠഡഢണതഥദധനപഫബഭമയരലവശഷസഹള",
    "telugu":     "కఖగఘఙచఛజఝఞటఠడఢణతథదధనపఫబభమయరలవశషసహళ",
}
# Vowels: a aa i ii u uu e ee ai o oo au
_VOWELS = {
    "sinhala":   "අආඉඊඋඌඑඒඓඔඕඖ",
    "malayalam": "അആഇഈഉഊഎഏഐഒഓഔ",
    "telugu":    "అఆఇఈఉఊఎఏఐఒఓఔ",
}
# Vowel signs: aa i ii u uu e ee ai o oo au, virama (hal kirima)
_SIGNS = {
    "sinhala":   "ාිීුූෙේෛොෝෞ්",
    "malayalam": "ാിീുൂെേൈൊോൌ്",
    "tamil":     "ாிீுூெேைொோௌ்",
    "telugu":    "ాిీుూెేైొోౌ్",
}

# Scripts without short e/o, or with gaps, are mapped by hand.
_EXTRA = {
    # Devanagari vowels and signs (its "e"/"o" are long sounds)
    "अ": "අ", "आ": "ආ", "इ": "ඉ", "ई": "ඊ", "उ": "උ", "ऊ": "ඌ", "ए": "ඒ", "ऐ": "ඓ",
    "ओ": "ඕ", "औ": "ඖ", "ा": "ා", "ि": "ි", "ी": "ී", "ु": "ු", "ू": "ූ", "े": "ේ",
    "ै": "ෛ", "ो": "ෝ", "ौ": "ෞ", "्": "්", "ं": "ං", "ः": "ඃ",
    # Tamil consonants that exist
    "க": "ක", "ங": "ඞ", "ச": "ච", "ஜ": "ජ", "ஞ": "ඤ", "ட": "ට", "ண": "ණ", "த": "ත",
    "ந": "න", "ப": "ප", "ம": "ම", "ய": "ය", "ர": "ර", "ல": "ල", "வ": "ව", "ஷ": "ෂ",
    "ஸ": "ස", "ஹ": "හ", "ள": "ළ", "ற": "ර", "ன": "න", "ழ": "ළ",
    # Tamil vowels
    "அ": "අ", "ஆ": "ආ", "இ": "ඉ", "ஈ": "ඊ", "உ": "උ", "ஊ": "ඌ", "எ": "එ", "ஏ": "ඒ",
    "ஐ": "ඓ", "ஒ": "ඔ", "ஓ": "ඕ", "ஔ": "ඖ",
    # Anusvara / visarga (the "ං" and "ඃ" signs)
    "ം": "ං", "ഃ": "ඃ", "ం": "ං", "ః": "ඃ",
    # Malayalam chillu letters (a consonant with a built-in hal kirima)
    "ൺ": "ණ්", "ൻ": "න්", "ർ": "ර්", "ൽ": "ල්", "ൾ": "ළ්",
}


def _build_map() -> dict[str, str]:
    table: dict[str, str] = {}
    for group in (_CONSONANTS, _VOWELS, _SIGNS):
        target = group["sinhala"]
        for script, letters in group.items():
            if script != "sinhala":
                table.update(zip(letters, target))
    table.update(_EXTRA)
    return table


LOOKALIKES = _build_map()

_SINHALA = re.compile(r"[඀-෿]")
# Letters of the other Indian scripts: Devanagari ... Malayalam (U+0900–U+0D7F)
_FOREIGN = re.compile(r"[ऀ-ൿ]")
_DIGIT_IN_WORD = re.compile(r"(?<=[඀-෿])\d+(?=[඀-෿])")


def foreign_chars(text: str) -> list[str]:
    """Letters that do not belong in Sinhala subtitle text."""
    return _FOREIGN.findall(text)


def has_foreign(text: str) -> bool:
    return bool(_FOREIGN.search(text))


def transliterate(text: str) -> str:
    """Swap look-alike letters for Sinhala ones; drop stray digits inside Sinhala words."""
    text = "".join(LOOKALIKES.get(ch, ch) for ch in text)
    return _DIGIT_IN_WORD.sub("", text)


def purity(texts: list[str]) -> float:
    """Share (0–1) of Indian-script letters that are really Sinhala."""
    sinhala = sum(len(_SINHALA.findall(t)) for t in texts)
    foreign = sum(len(_FOREIGN.findall(t)) for t in texts)
    return 1.0 if sinhala + foreign == 0 else sinhala / (sinhala + foreign)
