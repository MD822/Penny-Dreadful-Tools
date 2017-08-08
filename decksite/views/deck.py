from flask import session, url_for
import inflect
import titlecase

from decksite import deck_name
from decksite.data import archetype, deck
from decksite.view import View
from magic import fetcher, oracle
from shared import dtutil
from shared.pd_exception import InvalidDataException

# pylint: disable=no-self-use, too-many-instance-attributes
class Deck(View):
    def __init__(self, d):
        self._deck = d
        self.prepare_deck(self._deck)
        self.cards = d.all_cards()
        # This is called 'decks' and not something more sane because of limitations of Mustache and our desire to use a partial for decktable.
        self.decks = deck.get_similar_decks(d)
        self.has_similar = len(self.decks) > 0
        self.matches = deck.get_matches(d, True)
        for m in self.matches:
            m.display_date = dtutil.display_date(m.date)
            if m.opponent:
                m.opponent_url = url_for('person', person_id=m.opponent)
            else:
                m.opponent = 'BYE'
                m.opponent_url = False
            if m.opponent_deck_id:
                m.opponent_deck_url = url_for('decks', deck_id=m.opponent_deck_id)
            else:
                m.opponent_deck_url = False
            if m.opponent_deck:
                m.opponent_deck_name = deck_name.normalize(m.opponent_deck)
            else:
                m.opponent_deck_name = '-'
            if self.has_rounds():
                m.display_round = display_round(m)
        self._deck['maindeck'].sort(key=lambda x: oracle.deck_sort(x['card']))
        self._deck['sideboard'].sort(key=lambda x: oracle.deck_sort(x['card']))
        self.admin = session.get('admin', False)
        if self.admin:
            self.archetypes = archetype.load_archetypes_deckless(order_by='a.name')
            self.edit_archetype_url = url_for('edit_archetypes')
        self.cardhoarder_url = fetcher.cardhoarder_url(d)

    def has_matches(self):
        return len(self.matches) > 0

    def has_rounds(self):
        return self.has_matches() and self.matches[0].get('round')

    def og_title(self):
        return self._deck.name

    def og_url(self):
        return url_for('decks', deck_id=self._deck.id, _external=True)

    def og_description(self):
        if self.archetype_name:
            p = inflect.engine()
            archetype_s = titlecase.titlecase(p.a(self.archetype_name))
        else:
            archetype_s = 'A'
        description = '{archetype_s} deck by {author}'.format(archetype_s=archetype_s, author=self.person.decode('utf-8'))
        return description

    def __getattr__(self, attr):
        return getattr(self._deck, attr)

    def subtitle(self):
        return deck_name.normalize(self._deck)

    def sections(self):
        sections = []
        if self.creatures():
            sections.append({'name': 'Creatures', 'entries': self.creatures()})
        if self.spells():
            sections.append({'name': 'Spells', 'entries': self.spells()})
        if self.lands():
            sections.append({'name': 'Lands', 'entries': self.lands()})
        if self.sideboard():
            sections.append({'name': 'Sideboard', 'entries': self.sideboard()})
        return sections

    def creatures(self):
        return [entry for entry in self._deck.maindeck if entry['card'].is_creature()]

    def spells(self):
        return [entry for entry in self._deck.maindeck if entry['card'].is_spell()]

    def lands(self):
        return [entry for entry in self._deck.maindeck if entry['card'].is_land()]

    def sideboard(self):
        return self._deck.sideboard

def display_round(m):
    if not m.get('elimination'):
        return m.round
    if int(m.elimination) == 8:
        return 'QF'
    elif int(m.elimination) == 4:
        return 'SF'
    elif int(m.elimination) == 2:
        return 'F'
    else:
        raise InvalidDataException('Do not recognize round in {m}'.format(m=m))
