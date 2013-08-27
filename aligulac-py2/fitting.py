#!/usr/bin/python

'''
This script fits some model parameters.
'''

import sys, os, datetime
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aligulac.settings")

from ratings.models import Match
from ratings.tools import cdf
from aligulac.settings import PATH_TO_DIR

from math import floor, sqrt, log
from numpy import array
from scipy.optimize import fmin_l_bfgs_b

from django.db import connection

def write_params(maxdev, decdev, offweight):
    with open('aligulac/parameters.py', 'w') as f:
        f.write('# Rating system parameters\n')
        f.write('\n')
        f.write('RATINGS_INIT_DEV = %f\n' % maxdev)
        f.write('RATINGS_MIN_DEV = %f\n' % 0.01)
        f.write('RATINGS_DEV_DECAY = %f\n' % decdev)
        f.write('OFFLINE_WEIGHT = %f\n' % offweight)

def discrepancy():
    cur = connection.cursor()
    cur.execute('''SELECT ra.rating,  ra.rating_vp,  ra.rating_vt,  ra.rating_vz,
                          ra.dev,     ra.dev_vp,     ra.dev_vt,     ra.dev_vz,
                          rb.rating,  rb.rating_vp,  rb.rating_vt,  rb.rating_vz,
                          rb.dev,     rb.dev_vp,     rb.dev_vt,     rb.dev_vz,
                          m.rca,      m.rcb,         m.sca,         m.scb,
                          pa.country, pb.country
                   FROM   ratings_rating AS ra, ratings_rating AS rb,
                          ratings_player AS pa, ratings_player AS pb,
                          ratings_match AS m
                   WHERE  m.pla_id=pa.id AND m.plb_id=pb.id AND
                          ra.player_id=pa.id AND rb.player_id=pb.id AND
                          m.period_id=ra.period_id+1 AND m.period_id=rb.period_id+1 AND
                          m.rca<>'R' AND m.rcb<>'R' ''')

    disc_kr, disc_int, disc_cross = 0, 0, 0
    num_kr, num_int, num_cross = 0, 0, 0
    for r in cur.fetchall():
        ra = r[0] + r['PTZ'.index(r[17])+1]
        sa = r[4]**2 + r['PTZ'.index(r[17])+5]**2
        rb = r[8] + r['PTZ'.index(r[16])+9]
        sb = r[12]**2 + r['PTZ'.index(r[16])+13]**2

        p = cdf(ra-rb, scale=sqrt(1+sa+sb))
        disc = r[18] * log(p) + r[19] * log(1-p)

        if r[20] == 'KR' and r[21] == 'KR':
            disc_kr -= disc
            num_kr += 1
        elif r[20] != 'KR' and r[21] != 'KR':
            disc_int -= disc
            num_int += 1
        else:
            disc_cross -= disc
            num_cross += 1

    return (disc_kr/num_kr)**2 + (disc_int/num_int)**2 + (disc_cross/num_cross)**2

def objfun(x):
    print datetime.datetime.now(), 'Parameters:', x
    write_params(x[0], x[1], x[2])
    print datetime.datetime.now(), 'Computing ratings...'
    os.system(PATH_TO_DIR + 'recompute.py debug all > /dev/null')
    print datetime.datetime.now(), 'Computing discrepancy...'
    disc = discrepancy()
    print datetime.datetime.now(), x, '->', disc
    return disc

x0 = array([0.2488, 1.0395, 2.0155])
fmin_l_bfgs_b(objfun, x0, approx_grad=True, bounds=[(0, None), (0, None), (0, None)], epsilon=1e-3)
