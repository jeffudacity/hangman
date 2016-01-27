import re
import logging
import endpoints
from protorpc import remote, messages
from google.appengine.api import memcache
from google.appengine.api import taskqueue

from models import User, Phrase, Game, Score
from models import StringMessage, NewGameForm, GameForm, MakeMoveForm,\
    ScoreForms
from utils import get_by_urlsafe

NEW_GAME_REQUEST = endpoints.ResourceContainer(NewGameForm)
GET_GAME_REQUEST = endpoints.ResourceContainer(
        urlsafe_game_key=messages.StringField(1),)
MAKE_MOVE_REQUEST = endpoints.ResourceContainer(
    MakeMoveForm,
    urlsafe_game_key=messages.StringField(1),)

USER_REQUEST = endpoints.ResourceContainer(
    user_name=messages.StringField(1, required=True),
    email=messages.StringField(2, required=False)
    )

MEMCACHE_MOVES_REMAINING = 'MOVES_REMAINING'


@endpoints.api(name='hangman', version='v1')
class HangmanAPI(remote.Service):
    """Hangman Game API"""
    @endpoints.method(request_message=USER_REQUEST,
                      response_message=StringMessage,
                      path='user',
                      name='create_user',
                      http_method='POST')
    def create_user(self, request):
        """Create a User - requires a unique username."""
        if User.query(User.name == request.user_name).get():
            raise endpoints.ConflictException(
                    'A User with that name already exists!')
        user = User(name=request.user_name, email=request.email)
        user.put()

        success_message = 'User {} created!'.format(request.user_name)
        return StringMessage(message=success_message)

    @endpoints.method(request_message=NEW_GAME_REQUEST,
                      response_message=GameForm,
                      path='game',
                      name='new_game',
                      http_method='POST')
    def new_game(self, request):
        """Creates new game"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException(
                    'A User with that name does not exist!')
        phrase = Phrase.query(Phrase.phrase_or_word == request.phrase).get()
        if not phrase:
            phrase = Phrase(phrase_or_word=request.phrase)
            phrase.put()
        try:
            game = Game.new_game(user.key.urlsafe(),
                                 phrase.key.urlsafe(),
                                 request.num_of_mistakes_allowed)
            return game.to_form('Good luck playing Hangman!')
        except:
            raise

        # # Use a task queue to update the average attempts remaining.
        # # This operation is not needed to complete the creation of a new game
        # # so it is performed out of sequence.
        # taskqueue.add(url='/tasks/cache_average_attempts')
        # return game.to_form('Good luck playing Guess a Number!')

    @endpoints.method(request_message=GET_GAME_REQUEST,
                      response_message=GameForm,
                      path='game/{urlsafe_game_key}',
                      name='get_game',
                      http_method='GET')
    def get_game(self, request):
        """Return the current game state."""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if game:
            return game.to_form('Time to make a move!')
        else:
            raise endpoints.NotFoundException('Game not found!')

    @endpoints.method(request_message=MAKE_MOVE_REQUEST,
                      response_message=GameForm,
                      path='game/{urlsafe_game_key}',
                      name='make_move',
                      http_method='PUT')
    def make_move(self, request):
        """Makes a move. Returns a game state with message"""
        game = get_by_urlsafe(request.urlsafe_game_key, Game)
        if not game:
            raise endpoints.NotFoundException('Game not found!')

        if game.game_over:
            return game.to_form('Game already over!')

        # Users can only guess one letter at a time. Let's verify the
        # guess is a single character and is a letter from a-z or A-Z.
        assert re.match("^[A-Za-z]$", request.guess_letter), 'Guess must be a single letter.'

        # Users might accidentally guess a letter they have already
        # guessed so far. When that happens we should preserve the state
        # of the game.
        if request.guess_letter in game.letters_guessed_so_far:
            response_to_user = 'You have already guessed this letter: {}'
            response_to_user = response_to_user.format(request.guess_letter)
            return game.to_form(response_to_user)

        our_game_phrase = game.get_phrase()

        # Most likely the user will not guess a correct letter.
        if request.guess_letter not in our_game_phrase:
            game.letters_guessed_so_far += request.guess_letter
            game.mistakes_remaining -= 1

            # If the user has no mistakes remaining, the game is over.
            if game.mistakes_remaining == 0:
                game.end_game(won=False)
                response_to_user = 'Nope, you lose! The correct word was: {}'
                response_to_user = response_to_user.format(our_game_phrase)
            else:
                response_to_user = 'Nope, this letter is not in the word: {}'
                response_to_user = response_to_user.format(request.guess_letter)

            game.put()
            return game.to_form(response_to_user)

        # If the user did guess a correct letter then we need to update
        # the visible phrase.
        else:
            game.letters_guessed_so_far += request.guess_letter
            for (index, letter) in enumerate(our_game_phrase):
                if letter == request.guess_letter:
                    game.visible_so_far = game.visible_so_far[0:index] + request.guess_letter + game.visible_so_far[index + 1:]

            # If the visible phrase is identical to the game phrase then
            # we know the user has guessed all the letters.
            if game.visible_so_far == our_game_phrase:
                game.end_game(won=True)
                response_to_user = 'Congratulations, you win! You guessed the word: {}'
                response_to_user = response_to_user.format(our_game_phrase)
            else:
                response_to_user = 'Yes, "{}" was a letter in the word.'
                response_to_user = response_to_user.format(request.guess_letter)

            game.put()
            return game.to_form(response_to_user)

    @endpoints.method(response_message=ScoreForms,
                      path='scores',
                      name='get_scores',
                      http_method='GET')
    def get_scores(self, request):
        """Return all scores"""
        return ScoreForms(items=[score.to_form() for score in Score.query()])

    @endpoints.method(request_message=USER_REQUEST,
                      response_message=ScoreForms,
                      path='scores/user/{user_name}',
                      name='get_user_scores',
                      http_method='GET')
    def get_user_scores(self, request):
        """Returns all of an individual User's scores"""
        user = User.query(User.name == request.user_name).get()
        if not user:
            raise endpoints.NotFoundException(
                    'A User with that name does not exist!')
        scores = Score.query(Score.user == user.key)
        return ScoreForms(items=[score.to_form() for score in scores])

    @endpoints.method(response_message=StringMessage,
                      path='games/average_attempts',
                      name='get_average_attempts_remaining',
                      http_method='GET')
    def get_average_attempts(self, request):
        """Get the cached average moves remaining"""
        return StringMessage(message=memcache.get(MEMCACHE_MOVES_REMAINING) or '')

    @staticmethod
    def _cache_average_attempts():
        """Populates memcache with the average moves remaining of Games"""
        games = Game.query(Game.game_over == False).fetch()
        if games:
            count = len(games)
            total_attempts_remaining = sum([game.attempts_remaining
                                        for game in games])
            average = float(total_attempts_remaining)/count
            memcache.set(MEMCACHE_MOVES_REMAINING,
                         'The average moves remaining is {:.2f}'.format(average))


api = endpoints.api_server([HangmanAPI])
