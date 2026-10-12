"""Deterministic checks that no model can talk its way around."""

from __future__ import annotations

import re
import unicodedata

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
_WS = re.compile(r"\s+")


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_QUOTES)
    return _WS.sub(" ", s).strip().lower()


def quote_in(quote: str, document: str) -> bool:
    """True if the quote appears verbatim in the document (ignoring case, spacing and quote styles)."""
    q = normalize(quote).strip(" .\"'")
    return len(q) >= 12 and q in normalize(document)


_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def numbers_in(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM.findall(text or "")}


def unsupported_numbers(text: str, support: list[str]) -> set[str]:
    """Numbers in `text` that appear nowhere in the supporting claims and quotes."""
    allowed: set[str] = set()
    for s in support:
        allowed |= numbers_in(s)
    return {n for n in numbers_in(text) if n not in allowed}


_STOP = set("""about above after again against also among because been before being below between both could
during each from further have having into itself just more most other over same should since some such than
that their them then there these they this those through under until very were what when where which while
will with would your said says say according report reports reported""".split())


def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'-]{3,}", text.lower()) if w not in _STOP}


def title_similarity(a: str, b: str) -> float:
    ka, kb = keywords(a), keywords(b)
    if not ka or not kb:
        return 0.0
    return len(ka & kb) / min(len(ka), len(kb))


def excerpt(text: str, queries: list[str], max_chars: int = 6000) -> str:
    """The opening of a primary-source page plus the paragraphs most relevant to the claims."""
    paras = [p for p in text.split("\n") if len(p) > 30]
    if sum(len(p) for p in paras) <= max_chars:
        return "\n".join(paras)
    want = set()
    for q in queries:
        want |= keywords(q)
    scored = sorted(range(len(paras)), key=lambda i: -len(keywords(paras[i]) & want))
    chosen = {0, 1} & set(range(len(paras)))
    used = sum(len(paras[i]) for i in chosen)
    for i in scored:
        if i in chosen:
            continue
        if used + len(paras[i]) > max_chars:
            continue
        chosen.add(i)
        used += len(paras[i])
    return "\n".join(paras[i] for i in sorted(chosen))


# ---------------------------------------------------------------- entity guard

# Abbreviations and the forms a source may use instead. Lower case; matched as substrings. A dotted key is
# looked up without its periods ("U.S." uses the "us" entry).
_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "fed": ("federal reserve",), "fomc": ("federal open market committee",),
    "wsj": ("wall street journal",), "journal": ("wall street journal",),
    "gop": ("republican",), "republican": ("gop",), "republicans": ("gop",),
    "us": ("u.s.", "united states", "american"),
    "uk": ("u.k.", "britain", "british", "united kingdom"),
    "eu": ("european union",), "ecb": ("european central bank",), "boe": ("bank of england",),
    "boj": ("bank of japan",), "sec": ("securities and exchange commission",),
    "ice": ("immigration and customs enforcement", "immigration"), "doj": ("justice department",),
    "ftc": ("federal trade commission",), "opec": ("petroleum exporting",), "ai": ("artificial intelligence",),
    "rba": ("reserve bank of australia", "australia's central bank"), "g7": ("group of seven",),
    "qt": ("quantitative tightening",),
    "jgb": ("japanese government bond", "japan government bond", "japanese bond", "japan's bond", "japan's long-term bond"),
    "jgbs": ("japanese government bond", "japan government bond", "japanese bond", "japan's bond", "japan's long-term bond"),
    "treasury": ("treasuries",), "treasuries": ("treasury",), "nasdaq": ("nasdaq",),
    "trump": ("president",), "xi": ("xi",),
    # the WSJ headline said "SCOTUS" where the claim said "Supreme Court" (Tue Oct 6: the climate-lawsuits story lost)
    "scotus": ("supreme court",), "supreme": ("scotus",), "court": ("scotus",),
}

# A place and the adjective for it are the same name to a reader: "Yemeni forces" against "Yemen forces",
# "French yields" against "France's yields" (Mon Oct 5: four claims and lines rejected on such pairs).
_NATIONALITIES = """afghanistan afghan; africa african; albania albanian; algeria algerian; america american;
argentina argentine argentinian; armenia armenian; asia asian; australia australian; austria austrian;
azerbaijan azerbaijani; bahrain bahraini; bangladesh bangladeshi; belarus belarusian; belgium belgian;
bolivia bolivian; brazil brazilian; britain british; bulgaria bulgarian; cambodia cambodian; canada canadian;
chile chilean; china chinese; colombia colombian; croatia croatian; cuba cuban; cyprus cypriot; czechia czech;
denmark danish; ecuador ecuadorian; egypt egyptian; england english; estonia estonian; ethiopia ethiopian;
europe european; finland finnish; france french; georgia georgian; germany german; ghana ghanaian; greece greek;
hungary hungarian; iceland icelandic; india indian; indonesia indonesian; iran iranian; iraq iraqi; ireland irish;
israel israeli; italy italian; japan japanese; jordan jordanian; kazakhstan kazakh; kenya kenyan; korea korean;
kuwait kuwaiti; latvia latvian; lebanon lebanese; libya libyan; lithuania lithuanian; malaysia malaysian;
mexico mexican; mongolia mongolian; morocco moroccan; netherlands dutch; nigeria nigerian; norway norwegian;
oman omani; pakistan pakistani; palestine palestinian; panama panamanian; peru peruvian; philippines philippine filipino;
poland polish; portugal portuguese; qatar qatari; romania romanian; russia russian; saudi arabia saudi;
scotland scottish; serbia serbian; singapore singaporean; slovakia slovak; slovenia slovenian; spain spanish;
sri lanka sri lankan; sudan sudanese; sweden swedish; switzerland swiss; syria syrian; taiwan taiwanese;
thailand thai; tunisia tunisian; turkey turkish; ukraine ukrainian; emirates emirati; uruguay uruguayan;
uzbekistan uzbek; venezuela venezuelan; vietnam vietnamese; wales welsh; yemen yemeni; zambia zambian;
zimbabwe zimbabwean"""


def _nationality_aliases() -> dict[str, tuple[str, ...]]:
    out: dict[str, set[str]] = {}
    for entry in _NATIONALITIES.replace("\n", " ").split(";"):
        words = entry.split()
        # multi-word places: "saudi arabia saudi", "sri lanka sri lankan"
        if words[:2] == ["saudi", "arabia"]:
            forms = ["saudi arabia", "saudi"]
        elif words[:2] == ["sri", "lanka"]:
            forms = ["sri lanka", "sri lankan"]
        else:
            forms = words
        for f in forms:
            out.setdefault(f.split()[-1], set()).update(x for x in forms if x != f)
    return {k: tuple(sorted(v)) for k, v in out.items()}


for _k, _v in _nationality_aliases().items():
    _ENTITY_ALIASES[_k] = tuple(dict.fromkeys(_ENTITY_ALIASES.get(_k, ()) + _v))

# Titles, function words and other capitalised words that are not names.
_NOT_ENTITIES = set("""a an the and or but nor as at by for from in into of off on onto over to under up with
without after before during since until while this that these those it its he she they we you i his her their our
not no yes however meanwhile separately also both more most some several many few one two three four five six seven
eight nine ten first second third last next new old high low long short late early big small big
senator sen representative rep president secretary governor chairman chair chairwoman chief ceo cfo justice judge
ceos cfos coo coos cto ipo ipos
minister prime general attorney director commissioner spokesman spokeswoman spokesperson dr mr mrs ms
monday tuesday wednesday thursday friday saturday sunday january february march april may june july august
september october november december jan feb mar apr jun jul aug sep sept oct nov dec am pm et est edt gmt
q1 q2 q3 q4 inc corp co ltd plc llc group holdings
bloomberg reuters cnbc marketwatch ft wsj nyt times post news""".split())

_ENTITY = re.compile(r"[A-Z][A-Za-z0-9&.'’-]*")
_SENTENCE_START = re.compile(r"(?:^|[.;:!?]\s+|\(\s*)$")

# Words the collected news prints in lower case (Store.ordinary_words). A sentence-initial word in this set is an
# ordinary word even when a name follows it ("Deteriorating French bonds", "Major U.S. indexes"). Loaded once
# per run; empty means every sentence-initial word followed by a capital is held to the source, as before.
_ORDINARY: frozenset[str] = frozenset()


def set_ordinary_words(words) -> None:
    global _ORDINARY
    _ORDINARY = frozenset(words)


def _loose(s: str, hyphen: str = " ") -> str:
    """Spelling-insensitive form for comparing names: no periods, hyphens as spaces or dropped. "U.S." and
    "US", "C.H. Robinson" and "CH Robinson", "A.I.-focused" and "AI-focused", "AI-spending" and "AI spending",
    "G7" and "G-7" are the same name to a reader."""
    return _WS.sub(" ", s.replace(".", "").replace("-", hyphen)).strip()


def _entity_forms(token: str) -> tuple[list[str], list[str]]:
    """The token's own forms (singular and plural), and the other names for it (aliases)."""
    base = normalize(token).rstrip(".").removesuffix("'s").removesuffix("’s")
    forms = [base]
    if base.endswith("s"):
        forms.append(base[:-1])
    else:
        forms.append(base + "s")
    aliases = _ENTITY_ALIASES.get(base, ()) or _ENTITY_ALIASES.get(_loose(base), ())
    return [f for f in forms if len(f) >= 2], [a for a in aliases if len(a) >= 2]


def _alias_found(alias: str, haystack: str, loose_haystacks: tuple[str, str]) -> bool:
    """Another name for the token, as whole words with an optional plural or possessive: "Omani" is not
    found through "Oman" in "woman". (The token's own spelling still matches inside a longer word, as before.)"""
    if re.search(rf"(?<!\w){re.escape(alias)}(?:s|'s)?(?!\w)", haystack):
        return True
    for hyphen, loose_haystack in zip((" ", ""), loose_haystacks):
        la = _loose(alias, hyphen)
        if len(la) >= 2 and re.search(rf"(?<!\w){re.escape(la)}s?(?!\w)", loose_haystack):
            return True
    return False


def _name_found(form: str, haystack: str, loose_haystacks: tuple[str, str]) -> bool:
    """As printed (a substring, so plurals and possessives pass), or as the same letters spelled with or
    without periods and hyphens. The loose match must be a whole word, so "CH" is not found in "which"."""
    if form in haystack:
        return True
    for hyphen, loose_haystack in zip((" ", ""), loose_haystacks):
        lf = _loose(form, hyphen)
        if len(lf) >= 2 and re.search(rf"(?<!\w){re.escape(lf)}(?!\w)", loose_haystack):
            return True
    return False


def entities_in(text: str) -> list[str]:
    """Capitalised names in `text` worth holding to the source: skips titles, function words, and a
    capital at the start of a sentence that is there for grammar, not because it is a name: a lone one,
    or one the news prints in lower case elsewhere (see _ORDINARY).
    A hyphenated word with a lower-case second half ("Saudi-backed") is one token; with two capitals
    ("US-China") it is two."""
    out: list[str] = []
    for m in _ENTITY.finditer(text or ""):
        tok = m.group(0).rstrip(".'’")
        if "-" in tok:
            parts = tok.split("-")
            if all(p[:1].isupper() for p in parts if p):
                for p in parts:
                    if p and normalize(p) not in _NOT_ENTITIES:
                        out.append(p)
                continue
        low = normalize(tok).removesuffix("'s")
        if low in _NOT_ENTITIES or len(low) < 2:
            continue
        if _SENTENCE_START.search(text[:m.start()]) and not (tok[1:2].isupper() or "-" in tok):
            after = text[m.end():].lstrip()
            if not after[:1].isupper() or low in _ORDINARY:
                continue  # ordinary word capitalised only because it starts a sentence
        out.append(tok)
    return out


def unsupported_entities(text: str, support: list[str]) -> set[str]:
    """Names in `text` (people, places, bodies, companies, hyphenated modifiers) that appear in none
    of the supporting texts. "Saudi-backed" fails against "Saudi coalition"; "Fed" passes against
    "Federal Reserve"; "U.S." passes against "US"."""
    haystack = " " + normalize(" ".join(support)) + " "
    loose_haystacks = (_loose(haystack), _loose(haystack, ""))
    bad: set[str] = set()
    for tok in entities_in(text):
        forms, aliases = _entity_forms(tok)
        if not (any(_name_found(f, haystack, loose_haystacks) for f in forms)
                or any(_alias_found(a, haystack, loose_haystacks) for a in aliases)):
            bad.add(tok)
    return bad


# ---------------------------------------------------------------- certainty guard

def _word(p: str) -> re.Pattern:
    return re.compile(rf"(?<![\w-])(?:{p})(?![\w-])")


# Words that mark something as expected, planned or in progress rather than done, matched as whole words
# with their inflections: "expect" matches "expected" but not "expectations" or "better-than-expected",
# "aim" does not match "claim", and "weighed on stocks" is not "weighing a bid". Labels are what reports print.
_HEDGES: tuple[tuple[str, re.Pattern], ...] = tuple((label, _word(p)) for label, p in (
    ("heading for", "heading for"), ("headed for", "headed for"), ("heads for", "heads for"),
    ("on track", "on track"), ("on course", "on course"), ("on pace", "on pace"),
    ("set to", "set to"), ("set for", "set for"), ("said to", "said to"), ("plans to", "plans? to"),
    ("meant to", "meant to"), ("poised", "poised"),
    ("expect", r"(?<!than )expect(?:s|ed|ing)?"), ("could", "could"), ("might", "might"), ("would", "would"),
    ("planned", "planned"), ("planning", "planning"), ("consider", "consider(?:s|ed|ing)?"),
    ("weigh", r"weigh(?:s|ed|ing)?(?! (?:on|down)\b)"), ("reportedly", "reportedly"),
    ("likely", "(?:un)?likely"), ("potential", "potential(?:ly)?"), ("propos", "propos(?:e|es|ed|ing|al|als)"),
    ("seek", "seek(?:s|ing)?|sought"), ("aim", "aim(?:s|ed|ing)?"), ("intend", "intend(?:s|ed|ing)?"),
    ("hope", "hop(?:e|es|ed|ing)"), ("possible", "possibl(?:e|y)"),
))

# A hedge qualifies the words near it in its own clause, not every fact in the claim or the item: a line
# has dropped it only if it restates those words without a hedge of its own, and only when the hedged claim
# is the one the line restates most closely. A headline saying an Aramco CEO called stockpiles "scarily
# thin" restates that claim, not the one in which inventories "could take two years to rebuild".
_CLAUSE = re.compile(r"[,;:!?()]|(?<![A-Z])\.(?=\s|$)|\s[-–—]\s")
_REACH = 4  # words either side of a hedge that it qualifies


def hedges_in(text: str) -> set[str]:
    t = normalize(text)
    return {label for label, pat in _HEDGES if pat.search(t)}


def _stems(text: str) -> set[str]:
    words = (w.removesuffix("'s") for w in keywords(normalize(text)))
    return {w[:-1] if w.endswith("s") and not w.endswith("ss") else w for w in words}


def _hedged_words(claim: str) -> dict[str, set[str]]:
    """For each hedge in the claim, the content words it qualifies."""
    out: dict[str, set[str]] = {}
    for clause in _CLAUSE.split(claim):
        c = normalize(clause)
        for label, pat in _HEDGES:
            for m in pat.finditer(c):
                near = c[:m.start()].split()[-_REACH:] + c[m.end():].split()[:_REACH]
                out.setdefault(label, set()).update(_stems(" ".join(near)))
    return out


def dropped_hedges(text: str, claims: list[str]) -> set[str]:
    """Hedges in the cited claims whose hedged words the line restates without any hedge: a sign the line
    has upgraded 'heading for its worst week' to 'the worst week'. Empty when the line carries a hedge."""
    if hedges_in(text):
        return set()
    line = _stems(text)
    overlap = [len(_stems(c) & line) for c in claims]
    found: set[str] = set()
    for c, n in zip(claims, overlap):
        if n < max(overlap):
            continue  # the line restates another of its claims more closely
        for label, words in _hedged_words(c).items():
            if words & line:
                found.add(label)
    return found
