#!/usr/bin/python

'''
This script will recompute the ratings for a given period.

./period.py <period_id>

The script will yield an error message if there are untreated matches from previous periods, or if previous
periods are marked as not computed.

If you recompute all the ratings, consider commenting the last line (call to domination.py), see the comment
for more details.
'''

import sys, os
from numpy import *

# This is required for Django imports to work correctly
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aligulac.settings")

from django.db import connection, transaction
from django.db.models import Q, F
from ratings.models import Period, Player, Rating, Match
from ratings.tools import filter_active_ratings, start_rating
from aligulac.parameters import RATINGS_INIT_DEV, RATINGS_MIN_DEV, RATINGS_DEV_DECAY,\
                                OFFLINE_WEIGHT, KR_START, KR_END, KR_RATE

from rating import update, performance
from ratings.tools import cdf

# Parameters for rating computation
RACES = 'PTZ'
EXRACES = 'M' + RACES       # 'M' is 'MEAN'

KR_RATING = start_rating('KR', int(sys.argv[1]));

# This is a meta class holding information about rating computation
class CPlayer:
    def __init__(self):
        self.prev_rating = dict()       # A dict mapping EXRACES to ratings
        self.prev_dev = dict()          # A dict mapping EXRACES to RDs
        self.oppc = []                  # Opponent categories
        self.oppr = []                  # Opponent ratings
        self.oppd = []                  # Opponent RDs
        self.W = []                     # Number of wins
        self.L = []                     # Number of losses
        self.player = None              # Django Player object
        self.prev_rating_obj = None     # Django previous Rating object

    # Returns previous ratings in an array
    def get_rating_array(self):
        ret = []
        for r in EXRACES:
            ret.append(self.prev_rating[r])
        return array(ret)

    # Returns previous RDs in an array
    def get_dev_array(self):
        ret = []
        for r in EXRACES:
            ret.append(self.prev_dev[r])
        return array(ret)

def get_new_players(cplayers, period, prev):
    """Collects information about all new players, and adds them to the cplayers dict if not already there."""

    players = Player.objects.filter(Q(match_pla__period=period) | Q(match_plb__period=period))
    if prev is not None:
        players = players.exclude(rating__period=prev)

    for player in players.distinct():
        cp = CPlayer()
        cp.player = player
        cp.prev_rating_obj = None

        # Fill in the previous rating information
        for r in EXRACES:
            cp.prev_rating[r] = 0.0
            cp.prev_dev[r] = RATINGS_INIT_DEV

        if player.country == 'KR':
            cp.prev_rating['M'] = KR_RATING

        # Add to the dict
        cplayers[player.id] = cp

def get_existing_players(cplayers, prev):
    """Collects information about all players already rated, and adds them to the cplayers dict."""

    ratings = Rating.objects.filter(period=prev).select_related('player')
    for rating in ratings:
        cp = CPlayer()
        cp.player = rating.player
        cp.prev_rating_obj = rating

        # Fill in the previous rating information
        for r in RACES:
            cp.prev_rating[r] = rating.get_rating(r)
            cp.prev_dev[r] = rating.get_dev(r)
        cp.prev_rating['M'] = rating.get_rating()
        cp.prev_dev['M'] = rating.get_dev()

        # Add to the dict
        cplayers[rating.player.id] = cp

def decay_dev(cp):
    """Decays the RD of a player."""
    for r in EXRACES:
        cp.prev_dev[r] = min(sqrt(cp.prev_dev[r]**2 + RATINGS_DEV_DECAY**2), RATINGS_INIT_DEV)

def get_matches(cplayers, period):
    """
    Collects all results during a period and adds them to the cplayer objects.
    Returns the number of games played.
    """

    # Useful meta function to add a match to a cplayer object
    def add(cp_my, cp_op, rc_my, rc_op, sc_my, sc_op, weight=1.0):
        cp_my.oppc.append(RACES.index(rc_op))
        cp_my.oppr.append(cp_op.prev_rating['M'] + cp_op.prev_rating[rc_my])
        cp_my.oppd.append(sqrt(cp_op.prev_dev['M']**2 + cp_op.prev_dev[rc_my]**2))
        cp_my.W.append(weight * sc_my)
        cp_my.L.append(weight * sc_op)

    # Counter for number of games
    ngames = 0

    # Loop over all matches
    matches = Match.objects.filter(period=period).select_related('pla', 'plb')
    for m in matches:
        # Get cplayer objects
        cpa = cplayers[m.pla.id]
        cpb = cplayers[m.plb.id]

        # Set the played races for each player. For the vast majority of matches this should be a single item
        # list per player. When a player plays as random, or an unrecognized race, it will be treated as even
        # weight over all the three races
        rcas = [m.rca] if m.rca in RACES else RACES
        rcbs = [m.rcb] if m.rcb in RACES else RACES
        weight = float(1)/len(rcas)/len(rcbs)

        if m.offline:
            weight *= OFFLINE_WEIGHT

        # For each race combination, add information to the cplayer objects
        for ra in rcas:
            for rb in rcbs:
                add(cpa, cpb, ra, rb, m.sca, m.scb, weight)
                add(cpb, cpa, rb, ra, m.scb, m.sca, weight)

        # Count games
        ngames += m.sca + m.scb

    return ngames

def array_to_dict(ar):
    """Transforms a rating/RD dict to an array."""
    d = dict()
    d['M'] = ar[0]
    d['P'] = ar[1]
    d['T'] = ar[2]
    d['Z'] = ar[3]
    return d

# Main code for this script
if __name__ == '__main__':
    # Get period
    try:
        period = Period.objects.get(id=int(sys.argv[1]))
    except:
        print('No such period.')
        sys.exit(1)

    print('Period {0}: from {1} to {2}'.format(period.id, period.start, period.end))

    # Check that all previous periods are computed
    prev = Period.objects.filter(id__lt=period.id, computed=False)
    if prev.exists():
        print('Previous period #%i not computed. Aborting.' % prev[0].id)
        sys.exit(1)

    # Find the previous period if it exists
    try:
        prev = Period.objects.get(id=period.id-1)
    except:
        prev = None

    # Get all cplayer objects
    cplayers = dict()
    if prev:
        get_existing_players(cplayers, prev)
    get_new_players(cplayers, period, prev)

    # Update RDs since a period has passed
    for cp in cplayers.values():
        decay_dev(cp)

    # Collect match information
    num_games = get_matches(cplayers, period)
    print('Initialized: {0} players and {1} games. Updating...'.format(len(cplayers), num_games))

    # Update ratings
    num_retplayers = 0
    num_newplayers = 0
    for cp in cplayers.values():
        (newr, newd) = update(cp.get_rating_array(), cp.get_dev_array(),
                array(cp.oppr), array(cp.oppd), array(cp.oppc), array(cp.W), array(cp.L),
                cp.player.tag, False)

        cp.new_rating = array_to_dict(newr)
        cp.new_dev = array_to_dict(newd)

        perf = performance(array(cp.oppr), array(cp.oppd), array(cp.oppc), array(cp.W), array(cp.L))

        cp.comp_rat = array_to_dict(perf)

        # Count player as returning or new
        if len(cp.W) > 0 and cp.prev_rating_obj:
            num_retplayers += 1
        elif len(cp.W) > 0:
            num_newplayers += 1
    #sys.exit(0)

    # Get a table of existing rating objects
    existing = set()
    for i in Rating.objects.filter(period=period).values('player_id'):
        existing.add(i['player_id'])

    # Write ratings to database
    print('Saving ratings and bookkeping...')

    update_qvals, insert_qvals = [], []
    for cp in cplayers.values():
        tup = (cp.new_rating['M'],  cp.new_rating['P'],  cp.new_rating['T'],  cp.new_rating['Z'],
               cp.new_dev['M'],     cp.new_dev['P'],     cp.new_dev['T'],     cp.new_dev['Z'],
               cp.comp_rat['M'],    cp.comp_rat['P'],    cp.comp_rat['T'],    cp.comp_rat['Z'])

        if cp.player.id not in existing:
            to = insert_qvals
            tup += tup[0:8]
        else:
            to = update_qvals

        if len(cp.W) == 0 and cp.prev_rating_obj is not None:
            tup += (cp.prev_rating_obj.decay+1,)
        else:
            tup += (0,)

        tup += (cp.player.id, period.id)
        to.append(tup)

    cursor = connection.cursor()
    cursor.executemany('''UPDATE ratings_rating 
                          SET rating=%s,    rating_vp=%s,    rating_vt=%s,    rating_vz=%s,
                              dev=%s,       dev_vp=%s,       dev_vt=%s,       dev_vz=%s,
                              comp_rat=%s,  comp_rat_vp=%s,  comp_rat_vt=%s,  comp_rat_vz=%s,
                              decay=%s
                          WHERE player_id=%s AND period_id=%s''', update_qvals)
    cursor.executemany('''INSERT INTO ratings_rating 
                          (rating,     rating_vp,     rating_vt,     rating_vz,
                           dev,        dev_vp,        dev_vt,        dev_vz,
                           comp_rat,   comp_rat_vp,   comp_rat_vt,   comp_rat_vz,
                           bf_rating,  bf_rating_vp,  bf_rating_vt,  bf_rating_vz,
                           bf_dev,     bf_dev_vp,     bf_dev_vt,     bf_dev_vz,
                           decay,      player_id,     period_id)
                          VALUES
                          (%s, %s, %s, %s,
                           %s, %s, %s, %s,
                           %s, %s, %s, %s,
                           %s, %s, %s, %s,
                           %s, %s, %s, %s,
                           %s, %s, %s)''', insert_qvals)

    # Set all matches to treated
    Match.objects.filter(period=period).update(treated=True)

    # Compute OP/UP race
    def mean(a):
        return sum([f.rating for f in a])/len(a)
    rp = mean(Rating.objects.filter(period=period, player__race='P', decay__lt=4).order_by('-rating')[:5])
    rt = mean(Rating.objects.filter(period=period, player__race='T', decay__lt=4).order_by('-rating')[:5])
    rz = mean(Rating.objects.filter(period=period, player__race='Z', decay__lt=4).order_by('-rating')[:5])
    sp = cdf(rp-rt) + cdf(rp-rz)
    st = cdf(rt-rp) + cdf(rt-rz)
    sz = cdf(rz-rp) + cdf(rz-rt)
    period.dom_p = sp
    period.dom_t = st
    period.dom_z = sz

    # Write some period statistics
    period.num_retplayers = num_retplayers
    period.num_newplayers = num_newplayers
    period.num_games = num_games
    period.computed = True
    period.needs_recompute = False
    period.save()

    # Write ranks
    ratings = list(filter_active_ratings(Rating.objects.filter(period=period)))
    for index, rating in enumerate(sorted(ratings, key=lambda r: r.rating, reverse=True)):
        rating.position = index + 1
    for index, rating in enumerate(sorted(ratings, key=lambda r: r.rating + r.rating_vp, reverse=True)):
        rating.position_vp = index + 1
    for index, rating in enumerate(sorted(ratings, key=lambda r: r.rating + r.rating_vt, reverse=True)):
        rating.position_vt = index + 1
    for index, rating in enumerate(sorted(ratings, key=lambda r: r.rating + r.rating_vz, reverse=True)):
        rating.position_vz = index + 1
    for rating in ratings:
        rating.save()

    # Recompute the hall of fame
    # NOTE: If you compute several periods after one another, it might be wise to comment this and run it only
    # after the last rating computation, as it takes time to run and adds up quickly.
    # os.system('./domination.py')
