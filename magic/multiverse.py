import re

from magic import card, database, fetcher
from magic.database import db
from shared import dtutil
from shared.database import sqlescape

FORMAT_IDS = {}
CARD_IDS = {}

def init():
    current_version = fetcher.mtgjson_version()
    if current_version > database.version():
        print('Database update required')
        update_database(str(current_version))
        set_legal_cards()

def layouts():
    return ['normal', 'meld', 'split', 'phenomenon', 'token', 'vanguard', 'double-faced', 'plane', 'flip', 'scheme', 'leveler', 'aftermath']

def base_query(where_clause='(1 = 1)'):
    return """
        SELECT
            {card_queries},
            {face_queries},
            GROUP_CONCAT(face_name SEPARATOR '|') AS names,
            legalities,
            pd_legal,
            bug_desc,
            bug_class,
            bug_last_confirmed
            FROM
                (SELECT {card_props}, {face_props}, f.name AS face_name,
                SUM(CASE WHEN cl.format_id = {format_id} THEN 1 ELSE 0 END) > 0 AS pd_legal,
                GROUP_CONCAT({legality_code}) AS legalities,
                bugs.description AS bug_desc,
                bugs.classification AS bug_class,
                bugs.last_confirmed AS bug_last_confirmed
                FROM card AS c
                INNER JOIN face AS f ON c.id = f.card_id
                LEFT OUTER JOIN card_legality AS cl ON c.id = cl.card_id
                LEFT OUTER JOIN format AS fo ON cl.format_id = fo.id
                LEFT OUTER JOIN card_bugs AS bugs ON c.id = bugs.card_id
                GROUP BY f.id
                ORDER BY f.card_id, f.position)
            AS u
            WHERE u.id IN (SELECT c.id FROM card AS c INNER JOIN face AS f ON c.id = f.card_id WHERE {where_clause})
            GROUP BY u.id
    """.format(
        card_queries=', '.join(prop['query'].format(table='u', column=name) for name, prop in card.card_properties().items()),
        face_queries=', '.join(prop['query'].format(table='u', column=name) for name, prop in card.face_properties().items()),
        format_id=get_format_id('Penny Dreadful'),
        legality_code=db().concat(['fo.name', "':'", 'cl.legality']),
        card_props=', '.join('c.{name}'.format(name=name) for name in card.card_properties()),
        face_props=', '.join('f.{name}'.format(name=name) for name in card.face_properties() if name not in ['id', 'name']),
        where_clause=where_clause)


def update_database(new_version):
    db().begin()
    db().execute('DELETE FROM version')
    db().execute("""
    DELETE FROM card;
    DELETE FROM card_alias;
    DELETE FROM card_color;
    DELETE FROM card_color_identity;
    DELETE FROM card_legality;
    DELETE FROM card_subtype;
    DELETE FROM card_supertype;
    DELETE FROM card_type;
    DELETE FROM face;
    DELETE FROM printing;
    DELETE FROM `set`;
    """)
    cards = fetcher.all_cards()
    cards = add_hardcoded_cards(cards)
    melded_faces = []
    for _, c in cards.items():
        if c.get('layout') == 'meld' and c.get('name') == c.get('names')[2]:
            melded_faces.append(c)
        else:
            insert_card(c)
    for face in melded_faces:
        insert_card(face)
        first, second = face['names'][0:2]
        face['names'][0] = second
        face['names'][1] = first
        insert_card(face)
    sets = fetcher.all_sets()
    for _, s in sets.items():
        insert_set(s)
    check_layouts() # Check that the hardcoded list of layouts we're about to use is still valid.
    # mtgjson thinks that lands have a CMC of NULL so we'll work around that here.
    db().execute("UPDATE face SET cmc = 0 WHERE cmc IS NULL AND card_id IN (SELECT id FROM card WHERE layout IN ('normal', 'double-faced', 'flip', 'leveler', 'token', 'split'))")
    rs = db().execute('SELECT id, name FROM rarity')
    for row in rs:
        db().execute('UPDATE printing SET rarity_id = ? WHERE rarity = ?', [row['id'], row['name']])
    update_fuzzy_matching()
    update_bugged_cards(False)
    db().execute('INSERT INTO version (version) VALUES (?)', [new_version])
    db().commit()

def check_layouts():
    rs = db().execute('SELECT DISTINCT layout FROM card')
    if sorted([row['layout'] for row in rs]) != sorted(layouts()):
        print('WARNING. There has been a change in layouts. The update to 0 CMC may no longer be valid. Comparing {old} with {new}.'.format(old=sorted(layouts()), new=sorted([row['layout'] for row in rs])))

def update_fuzzy_matching():
    format_id = get_format_id('Penny Dreadful', True)
    if db().is_sqlite():
        db().execute('DROP TABLE IF EXISTS fuzzy')
        db().execute('CREATE VIRTUAL TABLE IF NOT EXISTS fuzzy USING spellfix1')
        sql = """INSERT INTO fuzzy (word, rank)
            SELECT LOWER(bq.name), bq.pd_legal
            FROM ({base_query}) AS bq
        """.format(base_query=base_query())
        db().execute(sql)
        sql = """INSERT INTO fuzzy (word, rank)
            SELECT LOWER(f.name), SUM(CASE WHEN cl.format_id = {format_id} THEN 1 ELSE 0 END) > 0
            FROM face AS f
            INNER JOIN card AS c ON f.card_id = c.id
            LEFT OUTER JOIN card_legality AS cl ON cl.card_id = c.id AND cl.format_id = {format_id}
            WHERE LOWER(f.name) NOT IN (SELECT word FROM fuzzy)
            GROUP BY f.id
        """.format(format_id=format_id)
        db().execute(sql)
        aliases = fetcher.card_aliases()
        for alias, name in aliases:
            db().execute('INSERT INTO fuzzy (word, soundslike) VALUES (LOWER(?), ?)', [name, alias])

def update_bugged_cards(use_transaction=True):
    bugs = fetcher.bugged_cards()
    if bugs is None:
        return
    if use_transaction:
        db().begin()
    db().execute("DELETE FROM card_bugs")
    for name, bug, classification, last_confirmed in bugs:
        last_confirmed_ts = dtutil.parse_to_ts(last_confirmed, '%Y-%m-%d %H:%M:%S', dtutil.UTC_TZ)
        card_id = db().value("SELECT card_id FROM face WHERE name = ?", [name])
        if card_id is None:
            print("UNKNOWN BUGGED CARD: {card}".format(card=name))
            continue
        db().execute("INSERT INTO card_bugs (card_id, description, classification, last_confirmed) VALUES (?, ?, ?, ?)", [card_id, bug, classification, last_confirmed_ts])
    if use_transaction:
        db().commit()

def insert_card(c):
    name = card_name(c)
    try:
        card_id = CARD_IDS[name]
    except KeyError:
        sql = 'INSERT INTO card ('
        sql += ', '.join(name for name, prop in card.card_properties().items() if prop['mtgjson'])
        sql += ') VALUES ('
        sql += ', '.join('?' for name, prop in card.card_properties().items() if prop['mtgjson'])
        sql += ')'
        values = [c.get(database2json(name)) for name, prop in card.card_properties().items() if prop['mtgjson']]
        # database.execute commits after each statement, which we want to avoid while inserting cards
        db().execute(sql, values)
        card_id = db().last_insert_rowid()
        CARD_IDS[name] = card_id
    # mtgjson thinks the text of Jhessian Lookout is NULL not '' but that is clearly wrong.
    if c.get('text', None) is None and c['layout'] in ['normal', 'token', 'double-faced', 'split']:
        c['text'] = ''
    c['nameAscii'] = card.unaccent(c.get('name'))
    c['cardId'] = card_id
    c['position'] = 1 if not c.get('names') else c.get('names', [c.get('name')]).index(c.get('name')) + 1
    sql = 'INSERT INTO face ('
    sql += ', '.join(name for name, prop in card.face_properties().items() if not prop['primary_key'])
    sql += ') VALUES ('
    sql += ', '.join('?' for name, prop in card.face_properties().items() if not prop['primary_key'])
    sql += ')'
    values = [c.get(database2json(name)) for name, prop in card.face_properties().items() if not prop['primary_key']]
    try:
        db().execute(sql, values)
    except database.DatabaseException:
        print(c)
        raise
    for color in c.get('colors', []):
        color_id = db().value('SELECT id FROM color WHERE name = ?', [color])
        db().execute('INSERT INTO card_color (card_id, color_id) VALUES (?, ?)', [card_id, color_id])
    for symbol in c.get('colorIdentity', []):
        color_id = db().value('SELECT id FROM color WHERE symbol = ?', [symbol])
        db().execute('INSERT INTO card_color_identity (card_id, color_id) VALUES (?, ?)', [card_id, color_id])
    for supertype in c.get('supertypes', []):
        db().execute('INSERT INTO card_supertype (card_id, supertype) VALUES (?, ?)', [card_id, supertype])
    for subtype in c.get('subtypes', []):
        db().execute('INSERT INTO card_subtype (card_id, subtype) VALUES (?, ?)', [card_id, subtype])
    for info in c.get('legalities', []):
        format_id = get_format_id(info['format'], True)
        db().execute('INSERT INTO card_legality (card_id, format_id, legality) VALUES (?, ?, ?)', [card_id, format_id, info['legality']])

def insert_set(s) -> None:
    sql = 'INSERT INTO `set` ('
    sql += ', '.join(name for name, prop in card.set_properties().items() if prop['mtgjson'])
    sql += ') VALUES ('
    sql += ', '.join('?' for name, prop in card.set_properties().items() if prop['mtgjson'])
    sql += ')'
    values = [date2int(s.get(database2json(name)), name) for name, prop in card.set_properties().items() if prop['mtgjson']]
    # database.execute commits after each statement, which we want to
    # avoid while inserting sets
    db().execute(sql, values)
    set_id = db().last_insert_rowid()
    for c in s.get('cards', []):
        card_id = CARD_IDS[card_name(c)]
        sql = 'INSERT INTO printing (card_id, set_id, '
        sql += ', '.join(name for name, prop in card.printing_properties().items() if prop['mtgjson'])
        sql += ') VALUES (?, ?, '
        sql += ', '.join('?' for name, prop in card.printing_properties().items() if prop['mtgjson'])
        sql += ')'
        values = [card_id, set_id] + [c.get(database2json(name)) for name, prop in card.printing_properties().items() if prop['mtgjson']]
        db().execute(sql, values)

def set_legal_cards(force=False, season=None):
    new_list = ['']
    try:
        new_list = fetcher.legal_cards(force, season)
    except fetcher.FetchException:
        pass
    if season is None:
        format_id = get_format_id('Penny Dreadful')
    else:
        format_id = get_format_id('Penny Dreadful {season}'.format(season=season), True)

    if new_list == [''] or new_list is None:
        return None

    db().execute('DELETE FROM card_legality WHERE format_id = ?', [format_id])
    sql = """INSERT INTO card_legality (format_id, card_id, legality)
        SELECT {format_id}, bq.id, 'Legal'
        FROM ({base_query}) AS bq
        WHERE name IN ({names})
    """.format(format_id=format_id, base_query=base_query(), names=', '.join(sqlescape(name) for name in new_list))
    db().execute(sql)
    # Check we got the right number of legal cards.
    n = db().value('SELECT COUNT(*) FROM card_legality WHERE format_id = ?', [format_id])
    if n != len(new_list):
        print("Found {n} pd legal cards in the database but the list was {len} long".format(n=n, len=len(new_list)))
        sql = 'SELECT bq.name FROM ({base_query}) AS bq WHERE bq.id IN (SELECT card_id FROM card_legality WHERE format_id = {format_id})'.format(base_query=base_query(), format_id=format_id)
        db_legal_list = [row['name'] for row in db().execute(sql)]
        print(set(new_list).symmetric_difference(set(db_legal_list)))
    return new_list

def database2json(propname: str) -> str:
    if propname == "system_id":
        propname = "id"
    return underscore2camel(propname)

def underscore2camel(s):
    return re.sub(r'(?!^)_([a-zA-Z])', lambda m: m.group(1).upper(), s)

def date2int(s, name):
    if name == 'release_date':
        return dtutil.parse_to_ts(s, '%Y-%m-%d', dtutil.WOTC_TZ)
    return s

# I'm not sure this belong here, but it's here for now.
def get_format_id(name, allow_create=False):
    if len(FORMAT_IDS) == 0:
        rs = db().execute('SELECT id, name FROM format')
        for row in rs:
            FORMAT_IDS[row['name']] = row['id']
    if name not in FORMAT_IDS.keys() and allow_create:
        db().execute('INSERT INTO format (name) VALUES (?)', [name])
        FORMAT_IDS[name] = db().last_insert_rowid()
    if name not in FORMAT_IDS.keys():
        return None
    return FORMAT_IDS[name]

def card_name(c):
    if c.get('layout') == 'meld':
        if c.get('name') != c.get('names')[2]:
            return c.get('name')
        else:
            return c.get('names')[0]
    return ' // '.join(c.get('names', [c.get('name')]))

def add_hardcoded_cards(cards):
    cards['Gleemox'] = {
        "text": "{T}: Add one mana of any color to your mana pool.\nThis card is banned.",
        "manacost": "{0}",
        "type": "Artifact",
        "layout": "normal",
        "types": ["Artifact"],
        "cmc": 0,
        'imageName': 'gleemox',
        "legalities": [],
        "name": "Gleemox",
        "printings": ["PRM"],
        "rarity": "Rare"
    }
    return cards
