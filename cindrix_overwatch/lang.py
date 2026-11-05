"""Guesses whether a headline is in English. No internet and no model: letters and common words only.

It leans toward "English" when unsure, so an English headline is never sent to the translator by mistake.
"""

import re

EN = set("the of and to in is for on that with as at by from are was has have will after over new says say amid "
         "against into its his her their be been not but more than us it an or this these those near over under "
         "killed attack attacks war troops military".split())
OTHER = set("""el la los las del en y que por con para una es se su al lo como más pero sus le les des du et est pour dans sur
avec qui au aux ce cette sont ont pas plus der die das und ist nicht mit von zu auf für ein eine den dem im auch sich
dass wird wurden o os as do da dos das em não uma são foi nos nas num il di che per con è nel della sono anche gli
een het van op te voor zijn niet naar och att som på av för det är har inte ett till en med de""".split())
OTHER -= EN


def looks_foreign(text):
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if len(letters) < 8:
        return False
    nonlatin = sum(1 for ch in letters if ord(ch) > 0x24F)
    if nonlatin / len(letters) > 0.3:
        return True
    words = re.findall(r"[^\W\d_]+", text.lower())
    en = sum(w in EN for w in words)
    other = sum(w in OTHER for w in words)
    accents = sum(1 for ch in letters if 0xC0 <= ord(ch) <= 0x24F)
    if other >= 2 and other > en:
        return True
    return other >= 1 and en == 0 and accents >= 1
