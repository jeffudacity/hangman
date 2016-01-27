import random

from datetime import date

import endpoints

from protorpc import messages
from google.appengine.ext import ndb

from utils import get_by_urlsafe


class User(ndb.Model):
    """User profile"""
    name = ndb.StringProperty(required=True)
    email = ndb.StringProperty()


class Phrase(ndb.Model):
    """Phrase object for guessing."""

    phrase_or_word = ndb.StringProperty(required=True)
    category = ndb.StringProperty(required=True, default='Miscellaneous')


class Game(ndb.Model):
    """Game object"""
    user = ndb.KeyProperty(required=True, kind='User')
    phrase_key = ndb.KeyProperty(required=True, kind='Phrase')
    visible_so_far = ndb.StringProperty(default='')
    mistakes_allowed = ndb.IntegerProperty(required=True, default=6)
    mistakes_remaining = ndb.IntegerProperty(required=True, default=6)
    letters_guessed_so_far = ndb.StringProperty(default='')
    game_over = ndb.BooleanProperty(required=True, default=False)

    @classmethod
    def new_game(cls, user_urlsafe_key, phrase_urlsafe_key, mistakes=6):
        """Create and return a new game."""
        phrase = get_by_urlsafe(phrase_urlsafe_key, Phrase)
        if not phrase:
            raise endpoints.NotFoundException('Phrase not found!')
        user = get_by_urlsafe(user_urlsafe_key, User)
        if not user:
            raise endpoints.NotFoundException('User not found!')
        visible_so_far = '?' * len(phrase.phrase_or_word)
        game = Game(user=user.key,
                    phrase_key=phrase.key,
                    visible_so_far=visible_so_far,
                    mistakes_allowed=mistakes,
                    mistakes_remaining=mistakes,
                    letters_guessed_so_far='',
                    game_over=False,
                    parent=phrase.key)
        game.put()
        return game

    def to_form(self, message):
        """Return a GameForm representation of the Game."""
        form = GameForm()
        form.urlsafe_key = self.key.urlsafe()
        form.user_name = self.user.get().name
        form.mistakes_remaining = self.mistakes_remaining
        form.visible_so_far = self.visible_so_far
        form.letters_guessed_so_far = self.letters_guessed_so_far
        form.game_over = self.game_over
        form.message = message
        return form

    def get_phrase(self):
        """Return the string representation of the game's phrase."""
        return self.phrase_key.get().phrase_or_word

    def end_game(self, won=False):
        """End the game: if won is True, the player won otherwise they lost."""
        self.game_over = True
        self.put()
        # Add the game to the score 'board'
        score = Score(user=self.user,
                      date=date.today(),
                      won=won,
                      mistakes_remaining=self.mistakes_remaining,
                      phrase_length=len(self.get_phrase())
                      )
        score.put()


class Score(ndb.Model):
    """Score object"""
    user = ndb.KeyProperty(required=True, kind='User')
    date = ndb.DateProperty(required=True)
    won = ndb.BooleanProperty(required=True)
    mistakes_remaining = ndb.IntegerProperty(required=True)
    phrase_length = ndb.IntegerProperty(required=True)

    def to_form(self):
        return ScoreForm(user_name=self.user.get().name,
                         won=self.won,
                         date=str(self.date),
                         mistakes_remaining=self.guesses,
                         phrase_length=self.phrase_length)


class GameForm(messages.Message):
    """GameForm for outbound game state information."""

    urlsafe_key = messages.StringField(1, required=True)
    mistakes_remaining = messages.IntegerField(2, required=True)
    visible_so_far = messages.StringField(3, required=True)
    letters_guessed_so_far = messages.StringField(4, required=True)
    game_over = messages.BooleanField(5, required=True)
    message = messages.StringField(6, required=True)
    user_name = messages.StringField(7, required=True)


class NewGameForm(messages.Message):
    """Used to create a new game"""
    user_name = messages.StringField(1, required=True)
    phrase = messages.StringField(2, required=True)
    num_of_mistakes_allowed = messages.IntegerField(3, default=6)


class MakeMoveForm(messages.Message):
    """Used to make a move in an existing game"""
    guess_letter = messages.StringField(1, required=True)


class ScoreForm(messages.Message):
    """ScoreForm for outbound Score information"""
    user_name = messages.StringField(1, required=True)
    date = messages.StringField(2, required=True)
    won = messages.BooleanField(3, required=True)
    mistakes_remaining = messages.IntegerField(4, required=True)
    phrase_length = messages.IntegerField(5, required=True)


class ScoreForms(messages.Message):
    """Return multiple ScoreForms"""
    items = messages.MessageField(ScoreForm, 1, repeated=True)


class StringMessage(messages.Message):
    """StringMessage-- outbound (single) string message"""
    message = messages.StringField(1, required=True)
