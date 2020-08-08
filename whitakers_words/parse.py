"""
parse.py (relating to Words's parse.adb)

Parse a word or list of input words and return word form and
definition

"""

__author__ = "Luke Hollis <luke@archimedes.digital>"
__license__ = "MIT License. See LICENSE."

import re
from copy import deepcopy

from whitakers_words.exceptions import WordsException
from whitakers_words.formatter import format_output

from whitakers_words.generated.dict_ids import dict_ids
from whitakers_words.generated.dict_keys import dict_keys
from whitakers_words.generated.stems import stems
from whitakers_words.generated.uniques import uniques
from whitakers_words.generated.inflects import inflects
from whitakers_words.data.addons import addons


class Parser:

    def __init__(self, **kwargs):
        """Provide a modular structure for loading the parser data"""
        self.wordlist = kwargs['wordlist'] if 'wordlist' in kwargs else dict_ids
        self.wordkeys = kwargs['wordkeys'] if 'wordkeys' in kwargs else dict_keys
        self.stems = kwargs['stems'] if 'stems' in kwargs else stems
        self.uniques = kwargs['uniques'] if 'uniques' in kwargs else uniques
        self.inflects = kwargs['inflects'] if 'inflects' in kwargs else inflects
        self.addons = kwargs['addons'] if 'addons' in kwargs else addons

    def parse(self, text):
        """
        Parse an input string as a Latin word and look it up in the Words dictionary.

        Return dictionary and grammatical data formatted in a similar manner as original
        Words program.
        """
        if not text.isalpha():
            raise WordsException("Text to be parsed must be a single Latin word")

        # Split text with enclitic into form + enclitic
        words = self.split_form_enclitic(text)

        parse_result = []

        for word in words:
            # Check base word against list of uniques
            if word['base'] in self.uniques:
                for unique_form in self.uniques[word['base']]:
                    # TODO: stems shouldn't be empty
                    parse_result.append({'w': unique_form, 'enclitic': word['encl'], 'stems': []})
            # Get regular words
            else:
                parse_result = self.analyze_forms(word)

        return {'word': text, 'defs': format_output(parse_result)}

    def analyze_forms(self, word, reduced=False):
        """
        Find all possible endings that may apply, so without checking congruence between word type and ending type
        """
        form = word['base']
        viable_inflections = []

        # the word may be undeclined, so add this as an option if the full form exists in the list of words
        if form in self.wordkeys:
            viable_inflections.append(self.inflects["0"][''])

        # Check against inflection list
        for inflect_length in range(1, min(8, len(form))):
            end_of_word = form[-inflect_length:]
            if str(inflect_length) in self.inflects and end_of_word in self.inflects[str(inflect_length)]:
                infl = self.inflects[str(inflect_length)][end_of_word]
                viable_inflections.append(infl)

        # Get viable combinations of stem + endings (+ enclitics)
        match_stems = self.match_stems_inflections(form, viable_inflections)

        for stemlist in match_stems.values():
            for stem in stemlist:
                stem['encl'] = word['encl']

        # Lookup dict info for found stems
        forms = self.lookup_stems(match_stems)

        if len(forms):
            return forms
        # If no hits and not already reduced, strip the word of any prefixes it may have, and try again
        if not reduced:
            return self.reduce(word)
        return []

    def match_stems_inflections(self, form, infls):
        """
        For each inflection that was a theoretical match, remove the inflection from the end of the word string
        and then check the resulting stem against the list of stems loaded in __init__
        """
        matched_stems = dict()
        # For each of the inflections that is a match, strip the inflection from the end of the word
        # and look up the stripped word (w) in the stems
        for infl_lemma in infls:
            if len(infl_lemma[0]['ending']):
                stem_lemma = form[:-len(infl_lemma[0]['ending'])]
            else:
                stem_lemma = form
            if stem_lemma in self.stems:
                stem_list = self.stems[stem_lemma]
                for stem_cand in stem_list:
                    for infl_cand in infl_lemma:
                        if self.check_match(stem_cand, infl_cand):
                            # If there's already a matched stem with that orthography
                            if stem_cand['orth'] in matched_stems:
                                for idx, matched_stem in enumerate(matched_stems[stem_cand['orth']]):
                                    if matched_stem['st']['wid'] == stem_cand['wid']:
                                        # if they're on the same lemma, multiple inflections exist for one stem
                                        matched_stem['infls'].append(infl_cand)
                                        matched_stems[stem_cand['orth']][idx] = matched_stem
                                        break
                                # for-else statement: else is only executed if for-loop is not interrupted by `break`
                                else:
                                    # so add a new lemma entry (separate wid) under the same orthography
                                    matched_stems[stem_cand['orth']].append({'st': stem_cand, 'infls': [infl_cand]})
                            else:
                                matched_stems[stem_cand['orth']] = [{'st': stem_cand, 'infls': [infl_cand]}]

        return matched_stems

    def check_match(self, stem, infl):
        """ Do custom checking mechanisms to see if the inflection and stem identify as the same part of speech """
        if infl['pos'] != stem['pos']:
            if infl['pos'] == "VPAR" and stem['pos'] == "V":
                try:
                    wrd = self.wordlist[int(stem['wid'])]
                    if not wrd:
                        return False  # probably an entry with a lot of meanings
                except IndexError:
                    return False  # must be part of uniques
                if infl['form'][8:12] == "PERF": # TODO probably broken now
                    return stem['orth'] == wrd['parts'][-1]
                else:
                    return stem['orth'] == wrd['parts'][0]
            return False
        if stem['pos'] == 'N':
            if infl['n'] == stem['n'] or (infl['n'][0] == stem['n'][0] and infl['n'][-1] == 0):
                return infl['form'][-1] == stem['form'][0] or infl['form'][-1] == 'C'
        elif stem['pos'] == 'ADV':
            if stem['form'] == 'X':
                try:
                    wrd = self.wordlist[int(stem['wid'])]
                    if not wrd:
                        return False  # probably an entry with a lot of meanings
                except IndexError:
                    return False  # must be part of uniques
                return stem['orth'] in wrd['parts']
            return stem['form'] == infl['form']
        return len(stem['n']) and infl['n'][0] == stem['n'][0]

    def lookup_stems(self, match_stems):
        """Find the word id mentioned in the stem in the dictionary"""
        results = []

        for stemlist in match_stems.values():
            for stem in stemlist:
                try:
                    dict_word = self.wordlist[int(stem['st']['wid'])]
                    if not dict_word:
                        continue
                except IndexError:
                    continue

                # Look for the word in the existing results
                is_in_results = False
                for word in results:
                    if dict_word['id'] == word['w']['id']:
                        # It is in the results list already, flag and then check if the stem is already in the stems
                        is_in_results = True

                        # Ensure the stem is not already in the results word stems
                        is_in_results_stems = False
                        for word_stem in word['stems']:
                            if word_stem == stem:
                                is_in_results_stems = True
                                break  # We have a match, break the inner loop
                        if not is_in_results_stems:
                            word['stems'].append(stem)
                        break  # If we matched a word in the results, break the outer loop

                # If the word is in the results already, we're done
                if not is_in_results:

                    # Check the VPAR / V relationship
                    if dict_word['pos'] == "V":

                        # If the stem doesn't match the 4th principle part, it's not VPAR
                        if dict_word['parts'].index(stem['st']['orth']) == 3:

                            # Remove "V" infls
                            stem = Parser.remove_extra_infls(stem, "V")

                        else:
                            # Remove "VPAR" infls
                            stem = Parser.remove_extra_infls(stem, "VPAR")

                    # Lookup word ends
                    # Need to Clone this object - otherwise self.wordlist is modified
                    dict_word_clone = deepcopy(dict_word)

                    # Finally, append new word to results
                    results.append({'w': dict_word_clone, 'enclitic': stem['encl'], 'stems': [stem]})
        return results

    def split_form_enclitic(self, s):
        """Split enclitic ending from word"""
        result = [{'base': s, 'encl': ''}]

        # Test the different tackons / packons as specified in addons.py
        if 'tackons' in self.addons:
            for e in self.addons['tackons']:
                if s.endswith(e['orth']):

                    # Est exception
                    if s != "est":
                        base = re.sub(e['orth'] + "$", "", s)
                        result.append({'base': base, 'encl': e})

        # which list do we get info from
        if s.startswith("qu"):
            lst = 'packons'
        else:
            lst = 'not_packons'

        if lst in self.addons:  # just to be sure
            for e in self.addons[lst]:
                if s.endswith(e['orth']):
                    base = re.sub(e['orth'] + "$", "", s)
                    # an enclitic without a base is not an enclitic
                    if base:
                        result.append({'base': base, 'encl': e})
                        # avoid double entry for -cumque and -que
                        break

        return result

    def reduce(self, option):
        """Reduce the stem with suffixes and try again"""
        out = []
        found_new_match = False
        s = option['base']
        # For each inflection match, check prefixes and suffixes
        if 'prefixes' in self.addons:
            for prefix in self.addons['prefixes']:
                if s.startswith(prefix['orth']):
                    s = re.sub("^" + prefix['orth'], "", s)
                    out.append({'w': prefix, 'stems': [], 'addon': "prefix"})
                    break
        if 'suffixes' in self.addons:
            for suffix in self.addons['suffixes']:
                if s.endswith(suffix['orth']):
                    s = re.sub(suffix['orth'] + "$", "", s)
                    out.append({'w': suffix, 'stems': [], 'addon': "suffix"})
                    break

        # Find forms with the 'reduced' flag set to true
        option['base'] = s
        out = self.analyze_forms(option, True)

        # Has reducing input string given us useful data?
        for word in out:
            if len(word['stems']) > 0:
                found_new_match = True

        # If not, return empty set
        if out and not found_new_match:
            out = []

        return out

    @staticmethod
    def remove_extra_infls(stem, remove_type="VPAR"):
        """Remove Vs or VPARs from a list of inflections"""
        stem_infls_copy = stem['infls'][:]

        for infl in stem_infls_copy:
            if infl['pos'] == remove_type:
                stem['infls'].remove(infl)

        return stem
