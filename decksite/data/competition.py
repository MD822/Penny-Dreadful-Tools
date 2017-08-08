from flask import url_for

from shared import dtutil
from shared.container import Container
from shared.database import sqlescape

from decksite.data import deck, guarantee
from decksite.database import db

def get_or_insert_competition(start_date, end_date, name, competition_type, url):
    start = start_date.timestamp()
    end = end_date.timestamp()
    competition_type_id = type_id(competition_type)
    values = [start, end, name, competition_type_id, url]
    sql = """
        SELECT id
        FROM competition
        WHERE start_date = %s AND end_date = %s AND name = %s AND competition_type_id = %s AND url = %s
    """
    competition_id = db().value(sql, values)
    if competition_id:
        return competition_id
    db().begin()
    sql = 'INSERT INTO competition (start_date, end_date, name, competition_type_id, url) VALUES (%s, %s, %s, %s, %s)'
    competition_id = db().insert(sql, values)
    if url is None:
        sql = 'UPDATE competition SET url = ? WHERE id = ?'
        db().execute(sql, [url_for('competition', competition_id=competition_id, _external=True), competition_id])
    db().commit()
    return competition_id

def type_id(competition_type):
    sql = 'SELECT id FROM competition_type WHERE name = %s'
    return db().value(sql, [competition_type])

def load_competition(competition_id):
    return guarantee.exactly_one(load_competitions('c.id = {competition_id}'.format(competition_id=sqlescape(competition_id))))

def load_competitions(where='1 = 1'):
    sql = """
        SELECT c.id, c.name, c.start_date, c.end_date, c.url,
        COUNT(d.id) AS num_decks,
        t.name AS type
        FROM competition AS c
        LEFT OUTER JOIN deck AS d ON c.id = d.competition_id
        LEFT OUTER JOIN competition_type as t ON t.id = c.competition_type_id
        WHERE {where}
        GROUP BY c.id
        ORDER BY c.start_date DESC, c.name
    """.format(where=where)
    competitions = [Container(r) for r in db().execute(sql)]
    for c in competitions:
        c.start_date = dtutil.ts2dt(c.start_date)
        c.end_date = dtutil.ts2dt(c.end_date)
    set_decks(competitions)
    return competitions

def set_decks(competitions):
    if competitions == []:
        return
    competitions_by_id = {c.id: c for c in competitions}
    where = 'd.competition_id IN ({ids})'.format(ids=', '.join(str(k) for k in competitions_by_id.keys()))
    decks = deck.load_decks(where)
    for c in competitions:
        c.decks = []
    for d in decks:
        competitions_by_id[d.competition_id].decks.append(d)
