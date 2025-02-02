import re
from enum import Enum
from typing import Any, Sequence, Tuple, Union

from .datalayer import DataLayer
from .datatypes import Addon, DictEntry, Inflect, Stem, Unique
from .enums import Gender, WordType, get_enum_value
from .matcher import Matcher


class WordsException(Exception):
    pass


class Inflection:
    def __init__(self, infl: Inflect, stem: Stem):
        self.wordType = get_enum_value("WordType", infl["pos"])
        self.category = infl["n"]
        self.stem = stem["orth"]
        self.affix = infl["ending"]
        self.features: dict[str, Enum] = {}
        self.analyse_features(infl["form"])
        self.override_features(stem)
        self.id = infl["iid"]

    def __repr__(self) -> str:
        return repr(self.__dict__)

    def analyse_features(self, features: Sequence[str]) -> None:
        # TODO patterns are emerging
        if self.wordType == WordType.N:
            lst = ["Case", "Number", "Gender"]
        elif self.wordType == WordType.NUM:
            lst = ["Case", "Number", "Gender", "NumeralType"]
        elif self.wordType == WordType.PRON:
            lst = ["Case", "Number", "Gender", "PronounType"]
        elif self.wordType == WordType.ADJ:
            lst = ["Case", "Number", "Gender", "Degree"]
        elif self.wordType == WordType.V:
            lst = ["Tense", "Voice", "Mood", "Person", "Number"]
        elif self.wordType == WordType.VPAR:
            lst = ["Case", "Number", "Gender", "Tense", "Voice"]
        elif self.wordType == WordType.ADV:
            lst = ["Degree"]
        else:
            return
        for idx, feature in enumerate(features[: len(lst)]):
            self.features[lst[idx]] = get_enum_value(lst[idx], feature)

    def override_features(self, stem: Stem) -> None:
        if self.wordType == WordType.N and stem["form"]:
            self.features["Gender"] = Gender[str(stem["form"][0])]

    def has_feature(self, feature: Enum) -> bool:
        return (
            type(feature).__name__ in self.features
            and self.features[type(feature).__name__] == feature
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Inflection):
            return NotImplemented
        return (
            self.affix == other.affix
            and self.wordType == other.wordType
            and self.category == other.category
            and self.features == other.features
        )


class UniqueInflection(Inflection):
    def __init__(self, unique: Unique):
        self.wordType = get_enum_value("WordType", unique["pos"])
        if "n" in unique:
            self.category = unique["n"]
        self.stem = unique["orth"]
        self.affix = ""
        self.features: dict[str, Enum] = {}
        self.analyse_features(unique["form"])


class Lexeme:
    def __init__(self, stem: Stem):
        self.id = stem["wid"]
        self.category: Sequence[Union[str, int]] = stem["n"]
        self.roots: Sequence[str] = []
        self.senses: Sequence[str] = []
        self.wordType = get_enum_value("WordType", stem["pos"])
        self.form = stem["form"]
        self.props = stem["props"]

    def __repr__(self) -> str:
        return repr(self.__dict__)


class UniqueLexeme(Lexeme):
    def __init__(self, unique: Unique):
        self.id = 0
        self.category = []
        self.roots = []
        self.senses = unique["senses"]
        self.wordType = get_enum_value("WordType", unique["pos"])


class Enclitic:
    def __init__(self, enclitic: Addon):
        self.text = enclitic["orth"]
        self.position = enclitic["pos"].split()
        self.senses = enclitic["senses"]
        self.id = enclitic.get("aid", 0)

    def __repr__(self) -> str:
        return repr(self.__dict__)


class Analysis:
    def __init__(
        self, lexeme: Lexeme, inflections: list[Inflection], enclitic: Enclitic = None
    ):
        self.lexeme = lexeme
        self.root = ""
        self.inflections = inflections
        self.enclitic = enclitic

    def __repr__(self) -> str:
        return repr(self.__dict__)

    def lookup_stem(self, wordlist: Sequence[DictEntry]) -> None:
        dict_word = wordlist[self.lexeme.id]
        if dict_word:  # guard for empty entries
            self.lexeme.roots = dict_word["parts"]
            self.lexeme.senses = dict_word["senses"]


class Form:
    def __init__(self, text: str, enclitic: Enclitic = None):
        self.text = text
        self.analyses: dict[int, Analysis] = {}
        self.enclitic = enclitic

    def __repr__(self) -> str:
        return repr(self.__dict__)

    def analyse_unique(self, unique_form: Unique) -> None:
        if self.analyses:
            self.analyses[0].inflections.append(UniqueInflection(unique_form))
        else:
            self.analyses = {
                0: Analysis(UniqueLexeme(unique_form), [UniqueInflection(unique_form)])
            }

    def analyse(self, data: DataLayer) -> None:
        """
        Find all possible endings that may apply, so without checking congruence between word type and ending type
        """
        viable_inflections: list[Inflect] = []

        # the word may be undeclined, so add this as an option if the full form exists in the list of words
        if self.text in data.wordkeys and self.text in data.stems:
            stem_list = data.stems[self.text]
            wordtypes = {x["pos"] for x in stem_list}
            # no need to check for VPAR, because there are no empty VPAR endings
            for wordtype in wordtypes:
                viable_inflections.extend(data.empty[wordtype])

        # Check against inflection list
        for inflect_length in range(1, min(8, len(self.text))):
            end_of_word = self.text[-inflect_length:]
            if (
                str(inflect_length) in data.inflects
                and end_of_word in data.inflects[str(inflect_length)]
            ):
                infl = data.inflects[str(inflect_length)][end_of_word]
                viable_inflections.extend(infl)

        # Get viable combinations of stem + endings (+ enclitics)
        analyses = self.match_stems_inflections(viable_inflections, data)

        for analysis in analyses.values():
            analysis.enclitic = self.enclitic
            analysis.lookup_stem(data.wordlist)
        if self.analyses:
            self.analyses.update(analyses)
        else:
            self.analyses = analyses
        # TODO reimplement reduce (see old_parser)

    def filter_good_analyses(self) -> None:
        # only use analyses where the lexeme was found
        self.analyses = dict(filter(self.filter_analysis, self.analyses.items()))

    def filter_analysis(self, analysis: Tuple[int, Analysis]) -> bool:
        if analysis[1].enclitic:
            enclitic = analysis[1].enclitic
            # TODO fix packons for real
            return (
                enclitic.position[0] in ("X", "PACK")
                or enclitic.position[0] == analysis[1].lexeme.wordType.name
            )
        return bool(analysis[1].lexeme.roots) or isinstance(
            analysis[1].lexeme, UniqueLexeme
        )

    def match_stems_inflections(
        self, viable_inflections: Sequence[Inflect], data: DataLayer
    ) -> dict[int, Analysis]:
        """
        For each inflection that was a theoretical match, remove the inflection from the end of the word string
        and then check the resulting stem against the list of stems loaded in __init__
        """
        matched_stems: dict[int, Analysis] = {}
        # For each of the inflections that is a match, strip the inflection from the end of the word
        # and look up the stripped word (w) in the stems
        for infl_cand in viable_inflections:
            if infl_cand["ending"]:
                stem_lemma = self.text[: -len(infl_cand["ending"])]
            else:
                stem_lemma = self.text
            if stem_lemma in data.stems:
                stem_list = data.stems[stem_lemma]
                for stem_cand in stem_list:
                    if Matcher(stem_cand, infl_cand).check():
                        word_id = stem_cand["wid"]
                        inflection = Inflection(infl_cand, stem_cand)
                        # If there's already a matched stem with that orthography
                        if word_id in matched_stems:
                            if inflection not in matched_stems[word_id].inflections:
                                matched_stems[word_id].inflections.append(inflection)
                        else:
                            matched_stems[word_id] = Analysis(
                                Lexeme(stem_cand), [inflection]
                            )
        return matched_stems


class Word:
    def __init__(self, text: str):
        self.text = text.lower()
        self.forms: Sequence[Form] = []

    def __repr__(self) -> str:
        return repr(self.__dict__)

    def analyse(self, data: DataLayer, apply_filter: bool = True) -> None:
        for form in self.forms:
            if form.text in data.uniques:
                for unique_form in data.uniques[form.text]:
                    form.analyse_unique(unique_form)
            # Get regular words
            form.analyse(data)
            # only use forms that get at least one valid analysis
            if apply_filter:
                form.filter_good_analyses()
        if apply_filter:
            self.filter_good_forms()

    def filter_good_forms(self) -> None:
        self.forms = list(filter(lambda form: form.analyses, self.forms))

    def split_form_enclitic(self, data: DataLayer) -> None:
        """Split enclitic ending from word"""
        result = [Form(self.text)]

        # Test the different tackons / packons as specified in addons.py
        result.extend(self.find_enclitic("tackons", data))

        # which list do we get info from
        if self.text.startswith("qu"):
            result.extend(self.find_enclitic("packons", data))
        else:
            result.extend(self.find_enclitic("not_packons", data))
        self.forms = result

    def find_enclitic(self, list_name: str, data: DataLayer) -> Sequence[Form]:
        result = []
        if list_name in data.addons:
            for affix in data.addons[list_name]:
                affix_text = affix["orth"]
                if self.text.endswith(affix_text):
                    base = re.sub(affix_text + "$", "", self.text)
                    # an enclitic without a base is not an enclitic
                    if base:
                        result.append(Form(base, Enclitic(affix)))
        return result

    def get_analyses(self) -> Sequence[Analysis]:
        return [item for form in self.forms for item in form.analyses.values()]


class Parser:
    def __init__(self, **kwargs: Any):
        self.data = DataLayer(**kwargs)

    def __repr__(self) -> str:
        return f'Parser(frequency="{self.data.frequency}")'

    def parse(self, text: str, apply_filters: bool = True) -> Word:
        if not text.isalpha():
            raise WordsException("Text to be parsed must be a single Latin word")
        result = Word(text)
        result.split_form_enclitic(self.data)
        result.analyse(self.data, apply_filters)
        return result
