import datetime
import subprocess
import urllib
from collections import Counter

from anytree.iterators import PreOrderIter
from flask import session, url_for

from magic import oracle, rotation, legality
from shared import dtutil
from shared.container import Container

from decksite import deck_name, template
from decksite.data import deck

# pylint: disable=no-self-use, too-many-public-methods
class View:
    def template(self):
        return self.__class__.__name__.lower()

    def content(self):
        return template.render(self)

    def page(self):
        return template.render_name('page', self)

    def home_url(self):
        return url_for('home')

    def css_url(self):
        return url_for('static', filename='css/pd.css', v=self.commit_id())

    def tooltips_url(self):
        return url_for('static', filename='js/tooltips.js', v=self.commit_id())

    def js_url(self):
        return url_for('static', filename='js/pd.js', v=self.commit_id())

    def menu(self):
        archetypes_badge = None
        if session.get('admin') is True:
            n = len(deck.load_decks('NOT d.reviewed'))
            if n > 0:
                archetypes_badge = {'url': url_for('edit_archetypes'), 'text': n}
        menu = [
            {'name': 'Decks', 'url': url_for('home')},
            {'name': 'Competitions', 'url': url_for('competitions')},
            {'name': 'People', 'url': url_for('people')},
            {'name': 'Cards', 'url': url_for('cards')},
            {'name': 'Archetypes', 'url': url_for('archetypes'), 'badge': archetypes_badge},
            {'name': 'Resources', 'url': url_for('resources')}
        ]
        if (rotation.next_rotation() - dtutil.now()) < datetime.timedelta(7):
            menu += [{'name': 'Rotation', 'url': url_for('rotation')}]
        menu += [
            {'name': 'About', 'url': url_for('about')},
            {'name': 'League', 'url': url_for('league'), 'has_submenu': True, 'submenu': [
                {'name': 'Sign Up', 'url': url_for('signup')},
                {'name': 'Report', 'url': url_for('report')},
                {'name': 'Records', 'url': url_for('current_league')}
            ]}
        ]
        return menu

    def favicon_url(self):
        return url_for('favicon', rest='.ico')

    def favicon_152_url(self):
        return url_for('favicon', rest='-152.png')

    def title(self):
        if not self.subtitle():
            return 'pennydreadfulmagic.com'
        return '{subtitle} – pennydreadfulmagic.com'.format(subtitle=self.subtitle())

    def subtitle(self):
        return None

    def prepare(self):
        self.prepare_decks()
        self.prepare_cards()
        self.prepare_competitions()
        self.prepare_people()
        self.prepare_archetypes()

    def prepare_decks(self):
        for d in getattr(self, 'decks', []):
            self.prepare_deck(d)
        for d in getattr(self, 'similar', []):
            self.prepare_deck(d)

    def prepare_deck(self, d):
        set_stars_and_top8(d)
        if d.get('colors') is not None:
            d.colors_safe = colors_html(d.colors, d.colored_symbols)
            d.name = deck_name.normalize(d)
        d.person_url = url_for('person', person_id=d.person_id)
        d.date_sort = dtutil.dt2ts(d.date)
        d.display_date = dtutil.display_date(d.date)
        d.show_record = d.wins or d.losses or d.draws
        if d.competition_id:
            d.competition_url = url_for('competition', competition_id=d.competition_id)
        d.url = url_for('decks', deck_id=d.id)
        d.export_url = url_for('export', deck_id=d.id)
        d.cmc_chart_url = url_for('cmc_chart', deck_id=d.id)
        if d.source_name == 'League' and d.wins + d.losses < 5 and d.competition_end_date > dtutil.now() and not d.get('retired', False):
            d.stars_safe = '<span title="Active in the current league">⊕</span> {stars}'.format(stars=d.stars_safe).strip()
            d.source_sort = '1'
        d.comp_row_len = len("{comp_name} (Piloted by {person}".format(comp_name=d.competition_name, person=d.person))
        if d.get('archetype_id', None):
            d.archetype_url = url_for('archetype', archetype_id=d.archetype_id)
        if d.omw is not None:
            d.omw = str(int(d.omw)) + '%'
        else:
            d.omw = ''
        d.has_legal_format = len(d.legal_formats) > 0
        d.pd_legal = 'Penny Dreadful' in d.legal_formats
        d.legal_icons = ''
        sets = legality.SEASONS
        if 'Penny Dreadful' in d.legal_formats:
            icon = rotation.last_rotation_ex()['code'].lower()
            n = sets.index(icon.upper()) + 1
            d.legal_icons += '<a href="{url}"><i class="ss ss-{code} ss-rare ss-grad">S{n}</i></a>'.format(url=url_for('season', season_id=n), code=icon, n=n)
        past_pd_formats = [fmt.replace('Penny Dreadful ', '') for fmt in d.legal_formats if 'Penny Dreadful ' in fmt]
        past_pd_formats.sort(key=lambda code: -sets.index(code))
        for code in past_pd_formats:
            n = sets.index(code.upper()) + 1
            d.legal_icons += '<a href="{url}"><i class="ss ss-{set} ss-common ss-grad">S{n}</i></a>'.format(url=url_for('season', season_id=n), set=code.lower(), n=n)
        if 'Commander' in d.legal_formats: # I think C16 looks the nicest.
            d.legal_icons += '<i class="ss ss-c16 ss-uncommon ss-grad">CMDR</i>'
        d.decklist = str(d).replace('\n', '<br>')

    def prepare_cards(self):
        for c in getattr(self, 'cards', []):
            self.prepare_card(c)
        for c in getattr(self, 'only_played_cards', []):
            self.prepare_card(c)

    def prepare_card(self, c):
        c.url = url_for('card', name=c.name)
        c.img_url = 'http://magic.bluebones.net/proxies/index2.php?c={name}'.format(name=urllib.parse.quote(c.name))
        c.pd_legal = c.legalities.get('Penny Dreadful', False)
        c.legal_formats = set(c.legalities.keys())
        c.has_legal_format = len(c.legal_formats) > 0
        if c.get('season') and c.get('all'):
            c.season.show_record = c.season.get('wins') or c.season.get('losses') or c.season.get('draws')
            c.all.show_record = c.all.get('wins') or c.all.get('losses') or c.all.get('draws')
        c.has_decks = len(c.get('decks', [])) > 0

    def prepare_competitions(self):
        for c in getattr(self, 'competitions', []):
            c.competition_url = url_for('competition', competition_id=c.id)
            c.display_date = dtutil.display_date(c.start_date)
            c.ends = '' if c.end_date < dtutil.now() else dtutil.display_date(c.end_date)
            c.date_sort = dtutil.dt2ts(c.start_date)

    def prepare_people(self):
        for p in getattr(self, 'people', []):
            p.url = url_for('person', person_id=p.id)
            if p.get('season') and p.get('all'):
                p.season.show_record = p.season.wins or p.season.losses or p.season.get('draws', None)
                p.all.show_record = p.all.wins or p.all.losses or p.all.get('draws', None)

    def prepare_archetypes(self):
        for a in getattr(self, 'archetypes', []):
            self.prepare_archetype(a, getattr(self, 'archetypes', []))

    def prepare_archetype(self, a, archetypes):
        num_most_common_cards_to_list = 10
        a.current = a.id == getattr(self, 'archetype', {}).get('id', None)
        if a.get('all') and a.get('season'):
            a.all.show_record = a.all.get('wins') or a.all.get('draws') or a.all.get('losses')
            a.season.show_record = a.season.get('wins') or a.season.get('draws') or a.season.get('losses')
        a.url = url_for('archetype', archetype_id=a.id)
        a.best_decks = Container({'decks': []})
        n = 3
        while len(a.best_decks.decks) == 0 and n >= 0:
            for d in a.get('decks', []):
                if d.get('stars_safe', '').count('★') >= n:
                    a.best_decks.decks.append(d)
            n -= 1
        counter = Counter()
        a.cards = []
        a.most_common_cards = []
        for d in a.get('decks', []):
            a.cards += d.maindeck + d.sideboard
            for c in d.maindeck:
                if not c['card'].type.startswith('Basic Land'):
                    counter[c['name']] += c['n']
        most_common_cards = counter.most_common(num_most_common_cards_to_list)
        cs = oracle.cards_by_name()
        for v in most_common_cards:
            self.prepare_card(cs[v[0]])
            a.most_common_cards.append(cs[v[0]])
        a.archetype_tree = PreOrderIter(a)
        for r in a.archetype_tree:
            # Prune branches we don't want to show
            if r.id not in [a.id for a in archetypes]:
                r.parent = None
            r['url'] = url_for('archetype', archetype_id=r['id'])
            # It perplexes me that this is necessary. It's something to do with the way NodeMixin magic works. Mustache doesn't like it.
            r['depth'] = r.depth

    def commit_id(self):
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'])


def colors_html(colors, colored_symbols):
    total = len(colored_symbols)
    if total == 0:
        return '<span class="mana" style="width: 3rem"></span>'
    s = ''
    for color in colors:
        n = colored_symbols.count(color)
        width = (3.0 - 0.1 * len(colors)) / total * n
        s += '<span class="mana mana-{color}" style="width: {width}rem"></span>'.format(color=color, width=width)
    return s

def set_stars_and_top8(d):
    if d.finish == 1:
        d.top8_safe = '<span title="Winner">①</span>'
        d.stars_safe = '★★★'
    elif d.finish == 2:
        d.top8_safe = '<span title="Losing Finalist">②</span>'
        d.stars_safe = '★★'
    elif d.finish == 3:
        d.top8_safe = '<span title="Losing Semifinalist">④</span>'
        d.stars_safe = '★★'
    elif d.finish == 5 and d.stage_reached > 0: # Don't show ⑧ for fifth place in a top 4 tournament.
        d.top8_safe = '<span title="Losing Quarterfinalist">⑧</span>'
        d.stars_safe = '★'
    else:
        d.top8_safe = ''
        if d.get('wins') is not None and d.get('losses') is not None:
            if d.wins - 5 >= d.losses:
                d.stars_safe = '★★'
            elif d.wins - 3 >= d.losses:
                d.stars_safe = '★'
            else:
                d.stars_safe = ''
        else:
            d.stars_safe = ''

    if len(d.stars_safe) > 0:
        d.stars_safe = '<span title="Success Rating">{stars}</span>'.format(stars=d.stars_safe)
