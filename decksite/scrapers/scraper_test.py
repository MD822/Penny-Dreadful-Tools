import pytest

from decksite.main import APP
from decksite.scrapers import tappedout, gatherling

## Disabled because tappedout is a pain.
# @pytest.mark.slowtest
# def test_tappedout():
#     APP.config["SERVER_NAME"] = "127:0.0.1:5000"
#     with APP.app_context():
#         tappedout.scrape()

@pytest.mark.slowtest
def test_gatherling():
    APP.config["SERVER_NAME"] = "127:0.0.1:5000"
    with APP.app_context():
        gatherling.scrape(5)

def test_manual_tappedout():
    APP.config["SERVER_NAME"] = "127:0.0.1:5000"
    with APP.app_context():
        tappedout.scrape_url('http://tappedout.net/mtg-decks/60-island/') # Best Deck
