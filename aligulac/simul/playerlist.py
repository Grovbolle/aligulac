from scipy.stats import norm
from math import sqrt

from ratings.models import Rating, Player

debug = False

def make_player(player):
    rats = Rating.objects.filter(player=player).order_by('-period__id')
    if rats.count == 0:
        pl = Player(player.tag, player.race, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6, 0.6, 0.6)
        pl.dbid = player.id
        return pl
    else:
        rat = rats[0]
        pl = Player(player.tag, player.race, rat.rating, rat.rating_vp, rat.rating_vt, rat.rating_vz,\
                    rat.dev, rat.dev_vp, rat.dev_vt, rat.dev_vz)
        pl.dbid = player.id
        return pl

class Player:

    def __init__(self, name='', race='', elo=0, elo_vp=0, elo_vt=0, elo_vz=0,\
                 dev=0.6, dev_vp=0.6, dev_vt=0.6, dev_vz=0.6, copy=None):
        if copy == None:
            self.name = name
            self.race = race
            self.elo = elo
            self.elo_race = {'P': elo_vp, 'T': elo_vt, 'Z': elo_vz}
            self.dev = dev
            self.dev_race = {'P': dev_vp, 'T': dev_vt, 'Z': dev_vz}
            self.flag = -1
        else:
            self.name = copy.name
            self.race = copy.race
            self.elo = copy.elo
            self.elo_race = copy.elo_race
            self.dev = copy.dev
            self.dev_race = copy.dev_race
            self.flag = copy.flag

    def prob_of_winning(self, opponent):
        mix = 0.3
        my_elo = self.elo + self.elo_race[opponent.race]
        op_elo = opponent.elo + opponent.elo_race[self.race]
        my_dev = self.dev**2 + self.dev_race[opponent.race]**2
        op_dev = opponent.dev**2 + opponent.dev_race[self.race]**2
        return norm.cdf(my_elo - op_elo, scale=sqrt(1+my_dev+op_dev))

    def copy(self):
        return Player(copy=self)