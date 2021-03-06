from magic import tournaments

from decksite.view import View

# pylint: disable=no-self-use
class Tournaments(View):
    def __init__(self):

        info = tournaments.next_tournament_info()
        self.next_tournament_name = info['next_tournament_name']
        self.next_tournament_time = info['next_tournament_time']

        self.tournaments = [
            {
                'name': 'Penny Dreadful Mondays',
                'host': 'stash86',
                'display_time': '7pm Eastern',
                'time': info['pdm_time'],
                'chat_room': '#PDM'
            },
            {
                'name': 'Penny Dreadful Thursdays',
                'host': 'silasary',
                'display_time': '7pm Eastern',
                'time': info['pdt_time'],
                'chat_room': '#PDT'
            },
            {
                'name': 'Penny Dreadful Sundays',
                'host': 'bakert99',
                'display_time': '1:30pm Eastern',
                'time': info['pds_time'],
                'chat_room': '#PDS'
            }
        ]

    def subtitle(self):
        return 'Tournaments'
