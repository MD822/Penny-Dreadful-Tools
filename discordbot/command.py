import collections
import glob
import os
import random
import re
import sys
import time

from typing import List

from discordbot import emoji
from find import search
from magic import card, oracle, fetcher, rotation, multiverse
from shared import configuration, dtutil
from shared.pd_exception import InvalidDataException

async def respond_to_card_names(message, bot):
    # Don't parse messages with Gatherer URLs because they use square brackets in the querystring.
    if 'gatherer.wizards.com' in message.content.lower():
        return
    queries = parse_queries(message.content)
    if len(queries) > 0:
        cards = cards_from_queries(queries)
        await bot.post_cards(cards, message.channel, message.author)

    matches = re.findall(r'https?://(?:www.)?tappedout.net/mtg-decks/(?P<slug>[\w-]+)/?', message.content, flags=re.IGNORECASE)
    for match in matches:
        data = {"url": "http://tappedout.net/mtg-decks/{slug}".format(slug=match)}
        fetcher.internal.post(fetcher.decksite_url('add'), data)

async def handle_command(message, bot):
    parts = message.content.split(' ', 1)
    method = find_method(parts[0])

    if parts[0].lower() in configuration.get('otherbot_commands').split(','):
        return

    args = ""
    if len(parts) > 1:
        args = parts[1]

    if method is not None:
        try:
            if method.__code__.co_argcount == 5:
                await method(Commands, bot, message.channel, args, message.author)
            elif method.__code__.co_argcount == 4:
                await method(Commands, bot, message.channel, args)
            elif method.__code__.co_argcount == 3:
                await method(Commands, bot, message.channel)
            elif method.__code__.co_argcount == 2:
                await method(Commands, bot)
            elif method.__code__.co_argcount == 1:
                await method(Commands)
        except Exception as e: # pylint: disable=broad-except
            print('Caught exception processing command `{cmd}`'.format(cmd=message.content))
            print(e)
            await bot.client.send_message(message.channel, 'I know the command `{cmd}` but I could not do that.'.format(cmd=parts[0]))
            await getattr(Commands, 'bug')(Commands, bot, message.channel, 'Command failed with {c}: {cmd}'.format(c=e.__class__.__name__, cmd=message.content), message.author)
    else:
        await bot.client.send_message(message.channel, 'Unknown command `{cmd}`. Try `!help`?'.format(cmd=parts[0]))

def find_method(name):
    cmd = name.lstrip('!').lower()
    if len(cmd) == 0:
        return
    method = [m for m in dir(Commands) if m == cmd or m == '_' + cmd]
    if len(method) == 0:
        method = [m for m in dir(Commands) if m.startswith(cmd) or m.startswith('_{cmd}'.format(cmd=cmd))]
    if len(method) > 0:
        return getattr(Commands, method[0])
    return None

def build_help(readme=False, cmd=None):
    def print_group(group):
        msg = ''
        for methodname in dir(Commands):
            if methodname.startswith("__"):
                continue
            method = getattr(Commands, methodname)
            if getattr(method, "group", None) != group:
                continue
            msg += '\n' + print_cmd(method, readme)
        return msg

    def print_cmd(method, verbose):
        if method.__doc__:
            if not method.__doc__.startswith('`'):
                return '`!{0}` {1}'.format(method.__name__, method.__doc__)
            return '{0}'.format(method.__doc__)
        elif verbose:
            return '`!{0}` No Help Available'.format(method.__name__)
        return "`!{0}`".format(method.__name__)

    if cmd:
        method = find_method(cmd)
        if method:
            return print_cmd(method, True)
        return "`{cmd}` is not a valid command.".format(cmd=cmd)

    msg = print_group("Commands")
    if readme:
        msg += "\n# Developer Commands"
        msg += print_group("Developer")
    return msg

def cmd_header(group):
    def decorator(func):
        setattr(func, "group", group)
        return func
    return decorator

# pylint: disable=too-many-public-methods
class Commands:
    """To define a new command, simply add a new method to this class.
    If you want !help to show the message, add a docstring to the method.
    Method parameters should be in the format:
    `async def commandname(self, bot, channel, args, author)`
    Where any argument after self is optional. (Although at least channel is usually needed)
    """

    @cmd_header("Commands")
    async def help(self, bot, channel, args):
        """`!help` Provides information on how to operate the bot."""
        if args:
            msg = build_help(cmd=args)
        else:
            msg = """[cardname] to get card details.
"""
            msg += build_help()
            msg += """

Suggestions/bug reports: <https://github.com/PennyDreadfulMTG/Penny-Dreadful-Discord-Bot/issues/>

Want to contribute? Send a Pull Request."""
        await bot.client.send_message(channel, msg)

    @cmd_header("Commands")
    async def random(self, bot, channel, args):
        """`!random` Request a random PD legal card
`!random X` Request X random PD legal cards."""
        number = 1
        if len(args) > 0:
            try:
                number = int(args.strip())
            except ValueError:
                pass
        cards = [oracle.cards_from_query(name)[0] for name in random.sample(oracle.legal_cards(), number)]
        await bot.post_cards(cards, channel)

    @cmd_header("Developer")
    async def update(self, bot, channel):
        """Forces an update to the legal card list"""
        oracle.legal_cards(force=True)
        await bot.client.send_message(channel, 'Reloaded list of legal cards.')

    @cmd_header("Developer")
    async def restartbot(self, bot, channel):
        """Restarts the bot."""
        await bot.client.send_message(channel, 'Rebooting!')
        sys.exit()

    @cmd_header("Commands")
    async def search(self, bot, channel, args, author):
        """`!search {query}` Search for cards, using a scryfall-style query."""
        try:
            cards = complex_search(args)
        except search.InvalidSearchException as e:
            await bot.client.send_message(channel, '{author}: {e}'.format(author=author.mention, e=e))
            return
        additional_text = ''
        if len(cards) > 10:
            additional_text = '<http://scryfall.com/search/?q=' + fetcher.internal.escape(args) + '>'
        await bot.post_cards(cards, channel, author, additional_text)

    @cmd_header("Commands")
    async def status(self, bot, channel):
        """`!status` Gives the status of MTGO, UP or DOWN."""
        status = fetcher.mtgo_status()
        await bot.client.send_message(channel, 'MTGO is {status}'.format(status=status))

    @cmd_header("Developer")
    async def echo(self, bot, channel, args):
        """Repeat after me..."""
        s = emoji.replace_emoji(args, bot.client)
        print('Echoing {s}'.format(s=s))
        await bot.client.send_message(channel, s)

    @cmd_header("Commands")
    async def barbs(self, bot, channel):
        """`!barbs` Gives Volvary's helpful advice for when to sideboard in Aura Barbs."""
        msg = "Heroic doesn't get that affected by Barbs. Bogles though. Kills their creature, kills their face."
        await bot.client.send_message(channel, msg)

    @cmd_header("Commands")
    async def quality(self, bot, channel):
        """`!quality` A helpful reminder about everyone's favorite way to play digital Magic"""
        msg = "**Magic Online** is a Quality™ Program."
        await bot.client.send_message(channel, msg)

    @cmd_header("Commands")
    async def rhinos(self, bot, channel):
        """`!rhinos` Anything can be a rhino if you try hard enough"""
        rhinos = []
        rhino_name = "Siege Rhino"
        if random.random() < 0.1:
            rhino_name = "Abundant Maw"
        rhinos.extend(oracle.cards_from_query(rhino_name))
        def find_rhino(query):
            cards = complex_search('f:pd {0}'.format(query))
            if len(cards) == 0:
                cards = complex_search(query)
            return random.choice(cards)
        rhinos.append(find_rhino('o:"copy of target creature"'))
        rhinos.append(find_rhino('o:"return target creature card from your graveyard to the battlefield"'))
        rhinos.append(find_rhino('o:"search your library for a creature"'))
        msg = "\nSo of course we have {rhino}.".format(rhino=rhinos[0].name)
        msg += " And we have {copy}. It can become a rhino, so that's a rhino.".format(copy=rhinos[1].name)
        msg += " Then there's {reanimate}. It can get back one of our rhinos, so that's a rhino.".format(reanimate=rhinos[2].name)
        msg += " And then we have {search}. It's a bit of a stretch, but that's a rhino too.".format(search=rhinos[3].name)
        await bot.post_cards(rhinos, channel, additional_text=msg)

    @cmd_header("Commands")
    async def rotation(self, bot, channel):
        """`!rotation` Give the date of the next Penny Dreadful rotation."""
        next_rotation = rotation.next_rotation()
        now = dtutil.now()
        if next_rotation > now:
            diff = next_rotation - now
            msg = "The next rotation is in {diff}".format(diff=dtutil.display_time(diff.total_seconds()))
            await bot.client.send_message(channel, msg)

    @cmd_header("Commands")
    async def _oracle(self, bot, channel, args, author):
        """`!oracle {name}` Give the Oracle text of the named card."""
        await single_card_text(bot, channel, args, author, oracle_text)

    @cmd_header("Commands")
    async def price(self, bot, channel, args, author):
        """`!price {name}` Get price information about the named card."""
        def price_info(c):
            try:
                p = fetcher.card_price(c.name)
            except fetcher.FetchException:
                return "Price unavailable"
            if p is None:
                return "Not available online"
            # Currently disabled
            s = '{price}'.format(price=format_price(p['price']))
            if float(p['low']) <= 0.05:
                s += ' (low {low}, high {high}'.format(low=format_price(p['low']), high=format_price(p['high']))
                if float(p['low']) <= 0.01:
                    s += ', {week}% this week, {month}% this month, {season}% this season'.format(week=round(float(p['week']) * 100.0), month=round(float(p['month']) * 100.0), season=round(float(p['season']) * 100.0))
                s += ')'
            age = dtutil.dt2ts(dtutil.now()) - p['time']
            if age > 60 * 60 * 2:
                s += '\nWARNING: price information is {display} old'.format(display=dtutil.display_time(age, 1))
            return s
        def format_price(p):
            if p is None:
                return 'Unknown'
            dollars, cents = str(round(float(p), 2)).split('.')
            return '{dollars}.{cents}'.format(dollars=dollars, cents=cents.ljust(2, '0'))
        await single_card_text(bot, channel, args, author, price_info)

    @cmd_header("Commands")
    async def legal(self, bot, channel, args, author):
        """Announce whether the specified card is legal or not."""
        await single_card_text(bot, channel, args, author, lambda c: '')

    @cmd_header("Commands")
    async def modofail(self, bot, channel, args, author):
        """Ding!"""
        if args.lower() == "reset":
            self.modofail.count = 0
        if hasattr(author, 'voice') and author.voice is not None and author.voice.voice_channel is not None:
            voice_channel = author.voice.voice_channel
            voice = channel.server.voice_client
            if voice is None:
                voice = await bot.client.join_voice_channel(voice_channel)
            elif voice.channel != voice_channel:
                voice.move_to(voice_channel)
            ding = voice.create_ffmpeg_player("ding.ogg")
            ding.start()
        if time.time() > self.modofail.last_fail + 60 * 60:
            self.modofail.count = 0
        self.modofail.count += 1
        self.modofail.last_fail = time.time()
        await bot.client.send_message(channel, ':bellhop: **MODO fail** {0}'.format(self.modofail.count))
    modofail.count = 0
    modofail.last_fail = time.time()

    @cmd_header("Commands")
    async def resources(self, bot, channel, args):
        """`!resources {args}` Link to useful pages related to `args`.
           Specifically – look for a section of pennydreadfulmagic.com that fits the description in {args}
           and links that match in /resources/.
           Examples:
               `!resources tournaments`
               `!resources card Hymn to Tourach`
               `!resources deck check`
               `!resources league`
               `!resources`
            """
        results = {}
        if len(args) > 0:
            results.update(resources_resources(args))
            results.update(site_resources(args))
        s = ''
        if len(results) == 0:
            s = 'PD resources: <{url}>'.format(url=fetcher.decksite_url('/resources/'))
        else:
            for url, text in results.items():
                s += '{text}: <{url}>\n'.format(text=text, url=url)
        await bot.client.send_message(channel, s)

    @cmd_header("Developer")
    async def clearimagecache(self, bot, channel):
        """Deletes all the cached images.  Use sparingly"""
        image_dir = configuration.get('image_dir')
        if not image_dir:
            return await bot.client.send_message(channel, 'Cowardly refusing to delete from unknown image_dir.')
        files = glob.glob('{dir}/*.jpg'.format(dir=image_dir))
        for file in files:
            os.remove(file)
        await bot.client.send_message(channel, '{n} cleared.'.format(n=len(files)))

    @cmd_header("Developer")
    async def notpenny(self, bot, channel, args):
        """Don't show PD Legality in this channel"""
        existing = configuration.get('not_pd')
        if args and args[0] == "server":
            cid = channel.server.id
        else:
            cid = channel.id
        if str(cid) not in existing.split(','):
            configuration.write('not_pd', "{0},{1}".format(existing, cid))

        await bot.client.send_message(channel, 'Disable PD marks')

    @cmd_header("Commands")
    async def bug(self, bot, channel, args, author):
        """Report a bug"""
        await bot.client.send_typing(channel)
        issue = fetcher.create_github_issue(args, author)
        if issue is None:
            await bot.client.send_message(channel, "Report issues at <https://github.com/PennyDreadfulMTG/Penny-Dreadful-Tools/issues/new>")
        else:
            await bot.client.send_message(channel, "Issue has been reported at <{url}>".format(url=issue.html_url))

    @cmd_header("Commands")
    async def invite(self, bot, channel):
        """Invite me to your server"""
        await bot.client.send_message(channel, "Invite me to your discord server by clicking this link: <https://discordapp.com/oauth2/authorize?client_id=224755717767299072&scope=bot&permissions=0>")

    @cmd_header("Commands")
    async def spoiler(self, bot, channel, args, author):
        """`!spoiler {cardname}`: Request a card from an upcoming set"""
        if len(args) == 0:
            await bot.client.send_message(channel, '{author}: Please specify a card name.'.format(author=author.mention))
            return

        sfcard = fetcher.internal.fetch_json('https://api.scryfall.com/cards/named?fuzzy={name}'.format(name=args))
        if sfcard['object'] == 'error':
            await bot.client.send_message(channel, '{author}: {details}'.format(author=author.mention, details=sfcard['details']))
            return
        imagename = '{set}_{number}'.format(set=sfcard['set'], number=sfcard['collector_number'])
        imagepath = '{image_dir}/{imagename}.jpg'.format(image_dir=configuration.get('image_dir'), imagename=imagename)
        fetcher.internal.store(sfcard['image_uri'], imagepath)
        text = emoji.replace_emoji('{name} {mana}'.format(name=sfcard['name'], mana=sfcard['mana_cost']), bot.client)
        await bot.client.send_file(channel, imagepath, content=text)
        try:
            oracle.valid_name(sfcard['name'])
        except InvalidDataException:
            c = {
                'layout': sfcard['layout'],
                'types': [], # This is wrong.  But whatever.
                'cmc': int(float(sfcard['cmc'])),
                'imageName': imagename,
                'legalities': [],
                'printings': [sfcard['set']],
                'rarity': sfcard['rarity'],
                'names': []
            }
            faces = sfcard.get('card_faces', [sfcard])
            names = [face['name'] for face in faces]
            for face in faces:
                c.update({
                    'name': face['name'],
                    'type': face['type_line'],
                    'text': face.get('oracle_text', ''),
                    'manaCost': face.get('mana_cost', None)
                })
                c['names'] = names
                multiverse.insert_card(c)

    @cmd_header("Commands")
    async def time(self, bot, channel, args, author):
        """`!time {location}` Show the current time in the specified location."""
        t = fetcher.time(args.strip())
        await bot.client.send_message(channel, '{author}: {time}'.format(author=author.mention, time=t))

    @cmd_header("Commands")
    async def pdm(self, bot, channel, args):
        """Alias for `!resources`."""
        # Because of the weird way we call and use methods on Commands we need ...
        # pylint: disable=too-many-function-args
        return await self.resources(self, bot, channel, args)

# Given a list of cards return one (aribtrarily) for each unique name in the list.
def uniqify_cards(cards):
    # Remove multiple printings of the same card from the result set.
    results = collections.OrderedDict()
    for c in cards:
        results[card.canonicalize(c.name)] = c
    return list(results.values())

def parse_queries(content: str) -> List[str]:
    queries = re.findall(r'\[?\[([^\]]*)\]\]?', content)
    return [query.lower() for query in queries]

def cards_from_queries(queries):
    all_cards = []
    for query in queries:
        cards = oracle.cards_from_query(query)
        if len(cards) > 0:
            all_cards.extend(cards)
    return all_cards

def complex_search(query):
    if query == '':
        return []
    print('Searching for {query}'.format(query=query))
    return search.search(query)

def roughly_matches(s1, s2):
    return simplify_string(s1).find(simplify_string(s2)) >= 0

def simplify_string(s):
    s = ''.join(s.split())
    return re.sub(r'[\W_]+', '', s).lower()

async def single_card_text(bot, channel, args, author, f):
    cards = list(oracle.cards_from_query(args))
    if len(cards) > 1:
        await bot.client.send_message(channel, '{author}: Ambiguous name.'.format(author=author.mention))
    elif len(cards) == 1:
        legal_emjoi = emoji.legal_emoji(cards[0])
        text = emoji.replace_emoji(f(cards[0]), bot.client)
        message = '**{name}** {legal_emjoi} {text}'.format(name=cards[0].name, legal_emjoi=legal_emjoi, text=text)
        await bot.client.send_message(channel, message)
    else:
        await bot.client.send_message(channel, '{author}: No matches.'.format(author=author.mention))

def oracle_text(c):
    return c.text

def site_resources(args):
    results = {}
    if ' ' in args.strip():
        area, detail = args.strip().split(' ', 1)
    else:
        area, detail = args.strip(), ''
    if area == 'card':
        area = 'cards'
    if area == 'person':
        area = 'people'
    sitemap = fetcher.sitemap()
    matches = [endpoint for endpoint in sitemap if endpoint.startswith('/{area}/'.format(area=area))]
    if len(matches) > 0:
        url = fetcher.decksite_url('/{area}/{detail}'.format(area=fetcher.internal.escape(area), detail=fetcher.internal.escape(detail)))
        results[url] = args
    return results

def resources_resources(args):
    results = {}
    words = args.split()
    resources = fetcher.resources()
    for title, items in resources.items():
        for text, url in items.items():
            asked_for_this_section_only = len(words) == 1 and roughly_matches(title, words[0])
            asked_for_this_section_and_item = len(words) == 2 and roughly_matches(title, words[0]) and roughly_matches(text, words[1])
            asked_for_this_item_only = len(words) == 1 and roughly_matches(text, words[0])
            if asked_for_this_section_only or asked_for_this_section_and_item or asked_for_this_item_only:
                results[url] = text
    return results
