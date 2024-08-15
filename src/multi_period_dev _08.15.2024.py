# Modified from https://github.com/sertalpbilal/FPL-Optimization-Tools
# 7/30/2022

import pandas as pd
import numpy as np
import sasoptpy as so
import requests
import os
import time
from subprocess import Popen, DEVNULL
from pathlib import Path
import json
from requests import Session
import random
import string


def get_random_id(n):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def xmin_to_prob(xmin, sub_on=0.5, sub_off=0.3):
    start = min( max ( (xmin - 25 * sub_on) / (90 * (1-sub_off) + 65 * sub_off - 25 * sub_on), 0.001), 0.999)
    return start + (1-start) * sub_on


def connect():
    print("This method is provided for people who want to automate login. However with 2FA changes, it is unlikely to work, and I'd suggest using team.json method from now on as explained in README file.")
    base_folder = Path()
    with open(base_folder / "../data/login.json") as f:
        credentials = json.load(f)
    session = Session()
    payload = {
        'password': credentials['password'],
        'login': credentials['email'],
        'redirect_uri': 'https://fantasy.premierleague.com/',
        'app': 'plfpl-web'
    }
    headers = {
        "user-agent": "Dalvik/2.1.0 (Linux; U; Android 6.0; Android SDK built for x86_64 Build/MASTER)",
        "cookie": "pl_euconsent-v2=CPUn1YtPUn1YtFCABAENBRCsAP_AAH_AAAwIF5wAQF5gXnABAXmAAAAA.YAAAAAAAAAAA; pl_euconsent-v2-intent-confirmed=^{^%^22tcf^%^22:^[755^]^%^2C^%^22oob^%^22:^[^]^}; pl_oob-vendors=^{^}; datadome=q_f99WYn0dSxMnuNGw8TQuIf2YeVio7m7Yk-jVBaWf43sM2v86YYVH17srelKLrR6B9ynB5V2z7pNs~jG6VKc~4u3up4WBrCYD6rekwuM3cRG8.9XbLGXAE4Cz~BWyv"
    }
    t = session.get('https://fantasy.premierleague.com/')
    time.sleep(1)
    v = session.post('https://users.premierleague.com/accounts/login/', data=payload, headers=headers, cookies=session.cookies)
    if v.status_code != 200:
        print("Login attempt failed, checking local file")
        if os.path.exists('team_regular.json'):
            return [session, None]
        print("""If you are getting this error, do the following: 
            - Open your browser and log in to FPL
            - After the login, go to following link (replace 'TEAM_ID' with your team ID)
              > https://fantasy.premierleague.com/api/my-team/TEAM_ID/
            - Create a file in this directory called 'team.json' and paste the content.
        """)
        return [None, None]
    else:
        r = session.get('https://fantasy.premierleague.com/api/me/')
        if r.status_code != 200:
            raise ValueError('Cannot read data')
        try:
            return [session, r.json()['player']['entry']]
        except:
            return [None, None]
        

def get_my_data(session, team_id=36602):
    r = session.get(f"https://fantasy.premierleague.com/api/my-team/{team_id}/")
    d = r.json()
    d['team_id'] = team_id
    return d


def prep_data(my_data, options):
    r = requests.get('https://fantasy.premierleague.com/api/bootstrap-static/')
    fpl_data = r.json()

    gw = 0

    for e in fpl_data['events']:
        if e['is_next']:
            gw = e['id']
            break
            

    horizon = options.get('horizon', 2)

    decay_base = options.get('decay_base', 0.84)

    element_data = pd.DataFrame(fpl_data['elements'])
    team_data = pd.DataFrame(fpl_data['teams'])
    elements_team = pd.merge(element_data, team_data, left_on='team', right_on='id')

    review_data = pd.read_csv(options.get('data_path', '../data/fplreview_md.csv'))
#     review_data = pd.read_csv('../data/fplreview_md.csv')
    review_data = review_data.fillna(0)
    review_data['review_id'] = review_data.index+1

    ownership_type = options.get('ownership_type', 'top1m')
#     ownership_type = 'overall'
    ownership_data = pd.read_csv(options.get('data_path', f'../data/ownership_{ownership_type}.csv'))
    ownership_data = ownership_data[['ID', 'Name', 'Current Own%']].copy()
#     ownership_data = pd.read_csv(f'../data/ownership_{ownership_type}.csv')
    ownership_review = pd.merge(ownership_data, review_data, on=['ID', 'Name'], how='outer')
    ownership_review.set_index(['ID'], inplace=True)

    next_gw = int(review_data.keys()[6].split('_')[0])
    last_gw = int(review_data.keys()[-3].split('_')[0])

    merged_data = pd.merge(elements_team, ownership_review, left_on='id_x', right_on='review_id')
    merged_data.rename(columns={'Current Own%': 'curr_own'}, inplace=True)

    original_keys = merged_data.columns.to_list()
    keys = [k for k in original_keys if "_Pts" in k]
    min_keys = [k for k in original_keys if "_xMins" in k]
    leverage_keys = [x.replace('_Pts', '_xNetGain') for x in keys]
    weighted_keys = [x.replace('_Pts', '_wPts') for x in keys]
    gain_keys = [x.replace('_Pts', '_xGain') for x in keys]
    loss_keys = [x.replace('_Pts', '_xLoss') for x in keys]
    xng_keys = [x.replace('_Pts', '_xNetGain') for x in keys]
    absxng_keys = [x.replace('_Pts', '_xAbsNG') for x in keys]

    # Get weighted weekly leverage, weighted, gain, and loss
    merged_data = merged_data.join(pd.concat([merged_data[k].mul(
        (1-2*merged_data['curr_own']/100) * (decay_base**(i))).to_frame(leverage_keys[i]) for i,k in enumerate(keys)],
                                                axis=1))
    merged_data = merged_data.join(pd.concat([merged_data[k].mul(
        (decay_base**(i))).to_frame(weighted_keys[i]) for i,k in enumerate(keys)],
                                                axis=1))
    merged_data = merged_data.join(pd.concat([merged_data[k].mul(
        ((1-merged_data['curr_own']/100) * decay_base**(i))).to_frame(gain_keys[i]) for i,k in enumerate(keys)],
                                                axis=1))
    merged_data = merged_data.join(pd.concat([merged_data[k].mul(
        (merged_data['curr_own']/100 * decay_base**(i))).to_frame(loss_keys[i]) for i,k in enumerate(keys)],
                                                axis=1))

    merged_data['tot_wpts'] = merged_data[weighted_keys].sum(axis=1)
    merged_data['net_gain'] = merged_data[leverage_keys].sum(axis=1)
    merged_data['xgain'] = merged_data[gain_keys].sum(axis=1)
    merged_data['xloss'] = merged_data[loss_keys].sum(axis=1)
#     merged_data = merged_data.loc[(merged_data[['tot_wpts', 'Team']] != 0).all(axis=1)].copy()
    # merged_df.sort_values(by=['net_gain'], ascending=False, inplace=True)

    # all_keys = [item for sublist in zip(keys, min_keys, weighted_keys, leverage_keys, gain_keys, loss_keys) for item in sublist]
    # column_names = ['Name', 'Team', 'Pos', 'curr_own', 'BV', 'SV', 'tot_wpts', 'net_gain', 'xgain', 'xloss']
    # column_names += all_keys

    # merged_data = merged_data[column_names]
    pos_order = {'G': 0, 'D': 1, 'M': 2, 'F': 3}

    # merged_df = merged_df[[column_names]]
    # merged_df = merged_df.dropna()
    # merged_df = merged_df.loc[merged_df['tot_pts'] > 0.5]
    merged_data = merged_data.loc[merged_data['SV'] < 98]

    for col in xng_keys:
        merged_data[col.replace('xNetGain', 'xAbsNG')] = abs(merged_data[col])

    merged_data['total_ev'] = merged_data[keys].sum(axis=1)
    merged_data['total_min'] = merged_data[min_keys].sum(axis=1)
    merged_data['total_xng'] = merged_data[xng_keys].sum(axis=1)
    merged_data['total_absxng'] = merged_data[absxng_keys].sum(axis=1)


    merged_data.rename(columns={'id_x': 'ID'}, inplace=True)
    merged_data.set_index(['ID'], inplace=True)
    merged_data.sort_values(by=['total_ev'], ascending=[False], inplace=True)

#     gain_keys = [k for k in original_keys if "_xGain" in k]
#     merged_data['total_xgain'] = merged_data[gain_keys].sum(axis=1)
    
    
    
    # Filter players by xMin
    initial_squad = [int(i['element']) for i in my_data['picks']]
    # safe_players = initial_squad + 
    xmin_lb = options.get('xmin_lb', 1)
    print(len(merged_data), "total players (before)")
    merged_data = merged_data[(merged_data['total_min'] >= xmin_lb) | (merged_data['review_id'].isin(initial_squad))].copy()
    print(len(merged_data), "total players (after)")

    if options.get('randomized', False):
        rng = np.random.default_rng(seed = options.get('seed'))
        gws = list(range(gw, min(39, gw+horizon)))
        for w in gws:
            noise = merged_data[f"{w}_Pts"] * (92 - merged_data[f"{w}_xMins"]) / 134 * rng.standard_normal(size=len(merged_data))
            merged_data[f"{w}_Pts"] = merged_data[f"{w}_Pts"] + noise

    type_data = pd.DataFrame(fpl_data['element_types']).set_index(['id'])

    buy_price = (merged_data['now_cost']/10).to_dict()
    sell_price = {i['element']: i['selling_price']/10 for i in my_data['picks']}
    price_modified_players = []
    
    preseason = options.get('preseason', False)
    if not preseason:
        for i in my_data['picks']:
            if buy_price[i['element']] != sell_price[i['element']]:
                price_modified_players.append(i['element'])
                print(f"Added player {i['element']} to list, buy price {buy_price[i['element']]} sell price {sell_price[i['element']]}")

    itb = my_data['transfers']['bank']/10
    if my_data['transfers']['limit'] is None:
        ft = 1
    else:
        ft = my_data['transfers']['limit'] - my_data['transfers']['made']
    if ft < 0:
        ft = 0
    # If wildcard is active, then you have: "status_for_entry": "active" under my_data['chips']
    for c in my_data['chips']:
        if c['name'] == 'wildcard' and c['status_for_entry'] == 'active':
            ft = 1
            options['use_wc'] = gw
            if options['chip_limits']['wc'] == 0:
                options['chip_limits']['wc'] = 1
            break

    return {
        'merged_data': merged_data,
        'team_data': team_data,
        'my_data': my_data,
        'type_data': type_data,
        'next_gw': gw,
        'initial_squad': initial_squad,
        'sell_price': sell_price,
        'buy_price': buy_price,
        'price_modified_players': price_modified_players,
        'itb': itb,
        'ft': ft
        }


def solve_multi_period_fpl(data, options):
    """
    Solves multi-objective FPL problem with transfers

    Parameters
    ----------
    data: dict
        Pre-processed data for the problem definition
    options: dict
        User controlled values for the problem instance
    """
    
    # Arguments
    problem_id = get_random_id(5)
#     problem_id = ''.join(random.choice(string.ascii_letters + string.digits) for i in range(5))

    horizon = options.get('horizon', 3)
#     horizon = 2
    objective = options.get('objective', 'regular')
#     objective = 'regular'
    decay_base = options.get('decay_base', 0.84)
#     decay_base = 0.84
    bench_weights = options.get('bench_weights', {0: 0.03, 1: 0.21, 2: 0.06, 3: 0.002}) # {0: 0.03, 1: 0.21, 2: 0.06, 3: 0.002}
#     bench_weights = {0: 0.03, 1: 0.21, 2: 0.06, 3: 0.002}
    wc_limit = options.get('wc_limit', 0)
#     wc_limit = 0
    ft_value = options.get('ft_value', 1.5)
#     ft_value = 1.5
    ft_value_list = options.get('ft_value_list', dict())
    itb_value = options.get('itb_value', 0.08)
#     itb_value = 0.08
    chip_limits = options.get('chip_limits', dict())
#     chip_limits = dict()
    booked_transfers = options.get('booked_transfers', [])
#     booked_transfers = []
    preseason = options.get('preseason', False)
#     preseason = True
    itb_loss_per_transfer = options.get('itb_loss_per_transfer', None)
    if itb_loss_per_transfer is None:
        itb_loss_per_transfer = 0
    ft = data.get('ft', 1)
#     ft = 1
    if ft <= 0:
        ft = 0
    
    
    # Data
    problem_name = f'mp_h{horizon}_{objective}_d{decay_base}'
    
    merged_data = data['merged_data']
    team_data = data['team_data']
    type_data = data['type_data']
    next_gw = data['next_gw']
    initial_squad = data['initial_squad']
    itb = data['itb']
    if preseason:
        itb = 100
        threshold_gw = 2
    else:
        threshold_gw = next_gw
        
    # Sets
    players = merged_data.index.to_list()
    element_types = type_data.index.to_list()
    teams = team_data['name'].to_list()
    gameweeks = list(range(next_gw, next_gw+horizon))
    all_gw = [next_gw-1] + gameweeks
    order = [0, 1, 2, 3]
    price_modified_players = data['price_modified_players']
#     price_modified_players = price_modified_players
    ft_states = [1, 2, 3, 4, 5]

    # Model
    model = so.Model(name=problem_name)

    # Variables
    squad = model.add_variables(players, all_gw, name='squad', vartype=so.binary)
    squad_fh = model.add_variables(players, gameweeks, name='squad_fh', vartype=so.binary)
    lineup = model.add_variables(players, gameweeks, name='lineup', vartype=so.binary)
    captain = model.add_variables(players, gameweeks, name='captain', vartype=so.binary)
    vicecap = model.add_variables(players, gameweeks, name='vicecap', vartype=so.binary)
    bench = model.add_variables(players, gameweeks, order, name='bench', vartype=so.binary)
    transfer_in = model.add_variables(players, gameweeks, name='transfer_in', vartype=so.binary)
    # transfer_out = model.add_variables(players, gameweeks, name='transfer_out', vartype=so.binary)
    transfer_out_first = model.add_variables(price_modified_players, gameweeks, name='tr_out_first', vartype=so.binary)
    transfer_out_regular = model.add_variables(players, gameweeks, name='tr_out_reg', vartype=so.binary)
    transfer_out = {
        (p,w): transfer_out_regular[p,w] + (transfer_out_first[p,w] if p in price_modified_players else 0) for p in players for w in gameweeks
    }
    in_the_bank = model.add_variables(all_gw, name='itb', vartype=so.continuous, lb=0)
    free_transfers = model.add_variables(all_gw, name='ft', vartype=so.integer, lb=0, ub=2)
    ft_above_ub = model.add_variables(gameweeks, name='ft_over', vartype=so.binary)
    ft_below_lb = model.add_variables(gameweeks, name='ft_below', vartype=so.binary)
    free_transfers_state = model.add_variables(gameweeks, ft_states, name='ft_state', vartype=so.binary)
    # Add a constraint for future transfers to be between 1 and 2
    penalized_transfers = model.add_variables(gameweeks, name='pt', vartype=so.integer, lb=0)
    aux = model.add_variables(gameweeks, name='aux', vartype=so.binary)
    transfer_count = model.add_variables(gameweeks, name='trc', vartype=so.integer, lb=0, ub=15)
    aux = model.add_variables(gameweeks, name='aux', vartype=so.binary)

#     use_wc = None
#     use_bb = None
#     use_fh = None

    use_wc = model.add_variables(gameweeks, name='use_wc', vartype=so.binary)
    use_bb = model.add_variables(gameweeks, name='use_bb', vartype=so.binary)
    use_fh = model.add_variables(gameweeks, name='use_fh', vartype=so.binary)
    
    # Dictionaries
    lineup_type_count = {(t,w): so.expr_sum(lineup[p,w] for p in players if merged_data.loc[p, 'element_type'] == t) for t in element_types for w in gameweeks}
    squad_type_count = {(t,w): so.expr_sum(squad[p,w] for p in players if merged_data.loc[p, 'element_type'] == t) for t in element_types for w in gameweeks}
    squad_fh_type_count = {(t,w): so.expr_sum(squad_fh[p,w] for p in players if merged_data.loc[p, 'element_type'] == t) for t in element_types for w in gameweeks}
    player_type = merged_data['element_type'].to_dict()
    # player_price = (merged_data['now_cost'] / 10).to_dict()

    sell_price = data['sell_price']
#     sell_price = sell_price

    buy_price = data['buy_price']
#     buy_price = buy_price

    sold_amount = {w: 
        so.expr_sum(sell_price[p] * transfer_out_first[p,w] for p in price_modified_players) +\
        so.expr_sum(buy_price[p] * transfer_out_regular[p,w] for p in players)
        for w in gameweeks}
    fh_sell_price = {p: sell_price[p] if p in price_modified_players else buy_price[p] for p in players}
    bought_amount = {w: so.expr_sum(buy_price[p] * transfer_in[p,w] for p in players) for w in gameweeks}
    points_player_week = {(p,w): merged_data.loc[p, f'{w}_Pts'] for p in players for w in gameweeks}
    wpoints_player_week = {(p,w): merged_data.loc[p, f'{w}_wPts'] for p in players for w in gameweeks}
    ng_player_week = {(p,w): merged_data.loc[p, f'{w}_xAbsNG'] for p in players for w in gameweeks}
    minutes_player_week = {(p,w): merged_data.loc[p, f'{w}_xMins'] for p in players for w in gameweeks}
    squad_count = {w: so.expr_sum(squad[p, w] for p in players) for w in gameweeks}
    squad_fh_count = {w: so.expr_sum(squad_fh[p, w] for p in players) for w in gameweeks}
    number_of_transfers = {w: so.expr_sum(transfer_out[p,w] for p in players) for w in gameweeks}
    number_of_transfers[next_gw-1] = 1
    transfer_diff = {w: number_of_transfers[w] - free_transfers[w] - 15 * use_wc[w] for w in gameweeks}

    ### Addition
    gain_player_week = {(p,w): merged_data.loc[p, f'{w}_xGain'] for p in players for w in gameweeks}
    
    # Initial conditions
    model.add_constraints((squad[p, next_gw-1] == 1 for p in initial_squad), name='initial_squad_players')
    model.add_constraints((squad[p, next_gw-1] == 0 for p in players if p not in initial_squad), name='initial_squad_others')
    model.add_constraint(in_the_bank[next_gw-1] == itb, name='initial_itb')
    model.add_constraint(free_transfers[next_gw] == ft, name='initial_ft')
    model.add_constraints((free_transfers[w] >= 1 for w in gameweeks if w > next_gw), name='future_ft_limit')

    # Constraints
    model.add_constraints((squad_count[w] == 15 for w in gameweeks), name='squad_count')
    model.add_constraints((squad_fh_count[w] == 15 * use_fh[w] for w in gameweeks), name='squad_fh_count')
    model.add_constraints((so.expr_sum(lineup[p,w] for p in players) == 11 + 4 * use_bb[w] for w in gameweeks), name='lineup_count')
    model.add_constraints((so.expr_sum(bench[p,w,0] for p in players if player_type[p] == 1) == 1 - use_bb[w] for w in gameweeks), name='bench_gk')
    model.add_constraints((so.expr_sum(bench[p,w,o] for p in players) == 1 - use_bb[w] for w in gameweeks for o in [1,2,3]), name='bench_count')
    model.add_constraints((so.expr_sum(captain[p,w] for p in players) == 1 for w in gameweeks), name='captain_count')
    model.add_constraints((so.expr_sum(vicecap[p,w] for p in players) == 1 for w in gameweeks), name='vicecap_count')
    model.add_constraints((lineup[p,w] <= squad[p,w] + use_fh[w] for p in players for w in gameweeks), name='lineup_squad_rel')
    model.add_constraints((bench[p,w,o] <= squad[p,w] + use_fh[w] for p in players for w in gameweeks for o in order), name='bench_squad_rel')
    model.add_constraints((lineup[p,w] <= squad_fh[p,w] + 1 - use_fh[w] for p in players for w in gameweeks), name='lineup_squad_fh_rel')
    model.add_constraints((bench[p,w,o] <= squad_fh[p,w] + 1 - use_fh[w] for p in players for w in gameweeks for o in order), name='bench_squad_fh_rel')
    model.add_constraints((captain[p,w] <= lineup[p,w] for p in players for w in gameweeks), name='captain_lineup_rel')
    model.add_constraints((vicecap[p,w] <= lineup[p,w] for p in players for w in gameweeks), name='vicecap_lineup_rel')
    model.add_constraints((captain[p,w] + vicecap[p,w] <= 1 for p in players for w in gameweeks), name='cap_vc_rel')
    model.add_constraints((lineup[p,w] + so.expr_sum(bench[p,w,o] for o in order) <= 1 for p in players for w in gameweeks), name='lineup_bench_rel')
    model.add_constraints((lineup_type_count[t,w] >= type_data.loc[t, 'squad_min_play'] for t in element_types for w in gameweeks), name='valid_formation_lb')
    model.add_constraints((lineup_type_count[t,w] <= type_data.loc[t, 'squad_max_play'] + use_bb[w] for t in element_types for w in gameweeks), name='valid_formation_ub')
    model.add_constraints((squad_type_count[t,w] == type_data.loc[t, 'squad_select'] for t in element_types for w in gameweeks), name='valid_squad')
    model.add_constraints((squad_fh_type_count[t,w] == type_data.loc[t, 'squad_select'] * use_fh[w] for t in element_types for w in gameweeks), name='valid_squad_fh')
    model.add_constraints((so.expr_sum(squad[p,w] for p in players if merged_data.loc[p, 'name'] == t) <= 3 for t in teams for w in gameweeks), name='team_limit')
    model.add_constraints((so.expr_sum(squad_fh[p,w] for p in players if merged_data.loc[p, 'name'] == t) <= 3 * use_fh[w] for t in teams for w in gameweeks), name='team_limit_fh')
    
    ## Transfer constraints
    model.add_constraints((squad[p,w] == squad[p,w-1] + transfer_in[p,w] - transfer_out[p,w] for p in players for w in gameweeks), name='squad_transfer_rel')
    model.add_constraints((in_the_bank[w] == in_the_bank[w-1] + sold_amount[w] - bought_amount[w] - (transfer_count[w] * itb_loss_per_transfer if w > next_gw else 0) for w in gameweeks), name='cont_budget')
    model.add_constraints((so.expr_sum(fh_sell_price[p] * squad[p,w-1] for p in players) + in_the_bank[w-1] >= so.expr_sum(fh_sell_price[p] * squad_fh[p,w] for p in players) for w in gameweeks), name='fh_budget')
    model.add_constraints((transfer_in[p,w] <= 1-use_fh[w] for p in players for w in gameweeks), name='no_tr_in_fh')
    model.add_constraints((transfer_out[p,w] <= 1-use_fh[w] for p in players for w in gameweeks), name='no_tr_out_fh')
    ## Free transfer constraints
    # 2024-2025 variation: min 1 / max 5 / roll over WC & FH
    raw_gw_ft = {w: free_transfers[w] - number_of_transfers[w] + 1 - use_wc[w] - use_fh[w] for w in gameweeks}
    model.add_constraints((free_transfers[w+1] <= raw_gw_ft[w] + 16 * ft_below_lb[w] for w in gameweeks if w+1 in gameweeks), name='newft1')
    model.add_constraints((free_transfers[w+1] <= 1 + 4 * (1-ft_below_lb[w]) for w in gameweeks if w+1 in gameweeks), name='newft2')
    model.add_constraints((free_transfers[w+1] >= raw_gw_ft[w] - 2 * ft_above_ub[w] for w in gameweeks if w+1 in gameweeks and w > 1), name='newft3')
    model.add_constraints((free_transfers[w+1] >= 5 - 5 * (1-ft_above_ub[w]) for w in gameweeks if w+1 in gameweeks and w > 1), name='newft4')
    
    model.add_constraints((free_transfers[w] == so.expr_sum(free_transfers_state[w,s] * s for s in ft_states) for w in gameweeks), name='ftsc1')
    model.add_constraints((so.expr_sum(free_transfers_state[w,s] for s in ft_states) == 1 for w in gameweeks), name='ftsc2')
    
    model.add_constraints((free_transfers[w] == aux[w] + 1 for w in gameweeks if w > threshold_gw), name='aux_ft_rel')
    model.add_constraints((free_transfers[w-1] - number_of_transfers[w-1] - 2 * use_wc[w-1] - 2 * use_fh[w-1] <= 2 * aux[w] for w in gameweeks if w > threshold_gw), name='force_aux_1')
    model.add_constraints((free_transfers[w-1] - number_of_transfers[w-1] - 2 * use_wc[w-1] - 2 * use_fh[w-1] >= aux[w] + (-14)*(1-aux[w]) for w in gameweeks if w > threshold_gw), name='force_aux_2')
    if preseason:
        model.add_constraint(free_transfers[threshold_gw] == 1, name='ps_initial_ft')
    model.add_constraints((penalized_transfers[w] >= transfer_diff[w] for w in gameweeks), name='pen_transfer_rel')
    
    ## Chip constraints
    model.add_constraints((use_wc[w] + use_fh[w] + use_bb[w] <= 1 for w in gameweeks), name='single_chip')
    model.add_constraints((aux[w] <= 1-use_wc[w-1] for w in gameweeks if w > next_gw), name='ft_after_wc')
    model.add_constraints((aux[w] <= 1-use_fh[w-1] for w in gameweeks if w > next_gw), name='ft_after_fh')

    model.add_constraint(so.expr_sum(use_wc[w] for w in gameweeks) <= chip_limits.get('wc', 0), name='use_wc_limit')
    model.add_constraint(so.expr_sum(use_bb[w] for w in gameweeks) <= chip_limits.get('bb', 0), name='use_bb_limit')
    model.add_constraint(so.expr_sum(use_fh[w] for w in gameweeks) <= chip_limits.get('fh', 0), name='use_fh_limit')
    model.add_constraints((squad_fh[p,w] <= use_fh[w] for p in players for w in gameweeks), name='fh_squad_logic')

    if options.get('use_wc', None) is not None:
        model.add_constraint(use_wc[options['use_wc']] == 1, name='force_wc')

    if options.get('use_bb', None) is not None:
        model.add_constraint(use_bb[options['use_bb']] == 1, name='force_bb')

    if options.get('use_fh', None) is not None:
        model.add_constraint(use_fh[options['use_fh']] == 1, name='force_fh')

    ## Multiple-sell fix
    model.add_constraints((transfer_out_first[p,w] + transfer_out_regular[p,w] <= 1 for p in price_modified_players for w in gameweeks), name='multi_sell_1')
    model.add_constraints((
        (wbar - next_gw + 1) * so.expr_sum(transfer_out_first[p,w] for w in gameweeks if w >= wbar) >=
        so.expr_sum(transfer_out_regular[p,w] for w in gameweeks if w >= wbar)
        for p in price_modified_players for wbar in gameweeks
    ), name='multi_sell_2')
    model.add_constraints((so.expr_sum(transfer_out_first[p,w] for w in gameweeks) <= 1 for p in price_modified_players), name='multi_sell_3')

    ## Transfer in/out fix
    model.add_constraints((transfer_in[p,w] + transfer_out[p,w] <= 1 for p in players for w in gameweeks), name='tr_in_out_limit')

    ## Optional constraints
    if options.get('banned', None) is not None:
        banned_players = options['banned']
        model.add_constraints((so.expr_sum(squad[p,w] for w in gameweeks) == 0 for p in banned_players), name='ban_player')

    if options.get('locked', None) is not None:
        locked_players = options['locked']
        model.add_constraints((squad[p,w] == 1 for p in locked_players for w in gameweeks), name='lock_player')

    if options.get("no_future_transfer"):
        model.add_constraint(so.expr_sum(transfer_in[p,w] for p in players for w in gameweeks if w > next_gw and w != options.get('use_wc')) == 0, name='no_future_transfer')

    if options.get("num_transfers", None) is not None:
        model.add_constraint(so.expr_sum(transfer_in[p,next_gw] for p in players) == options['num_transfers'], name='tr_limit')

    if options.get("hit_limit", None) is not None:
        model.add_constraint(so.expr_sum(penalized_transfers[w] for w in gameweeks) <= options['hit_limit'], name='horizon_hit_limit')

    if options.get("future_transfer_limit", None) is not None:
        model.add_constraint(so.expr_sum(transfer_in[p,w] for p in players for w in gameweeks if w > next_gw and w != options.get('use_wc')) <= options['future_transfer_limit'], name='future_tr_limit')

    if options.get("no_transfer_gws", None) is not None:
        if len(options['no_transfer_gws']) > 0:
            model.add_constraint(so.expr_sum(transfer_in[p,w] for p in players for w in options['no_transfer_gws']) == 0, name='banned_gws_for_tr')

    for booked_transfer in booked_transfers:
        transfer_gw = booked_transfer.get('gw', None)

        if transfer_gw is None:
            continue

        player_in = booked_transfer.get('transfer_in', None)
        player_out = booked_transfer.get('transfer_out', None)

        if player_in is not None:
            model.add_constraint(transfer_in[player_in, transfer_gw] == 1,
                                 name=f'booked_transfer_in_{transfer_gw}_{player_in}')
        if player_out is not None:
            model.add_constraint(transfer_out[player_out, transfer_gw] == 1,
                                 name=f'booked_transfer_out_{transfer_gw}_{player_out}')

    # FT gain
    ft_state_value = {}
    for s in ft_states:
        ft_state_value[s] = ft_state_value.get(s-1, 0) + ft_value_list.get(str(s), ft_value)
    print(f"Using FT state values of {ft_state_value}")
    gw_ft_value = {w: so.expr_sum(ft_state_value[s] * free_transfers_state[w,s] for s in ft_states) for w in gameweeks}
    gw_ft_gain = {w: gw_ft_value[w] - gw_ft_value.get(w-1, 0) for w in gameweeks}        
            
    # Objectives

    ## NEW
    # Define the total points for selected players for each gameweek
    hit_cost = options.get('hit_cost', 4)
    gw_xp = {w: so.expr_sum(points_player_week[p,w] * (lineup[p,w] + captain[p,w] + 0.1*vicecap[p,w] + so.expr_sum(bench_weights[o] * bench[p,w,o] for o in order)) for p in players) for w in gameweeks}

    # Define the total xloss for unselected players for each gameweek
    gw_xgain = {w: so.expr_sum(merged_data.loc[p, f'{w}_xGain'] * (lineup[p,w] + captain[p,w] + 0.1*vicecap[p,w] + so.expr_sum(bench_weights[o] * bench[p,w,o] for o in order)) for p in players) for w in gameweeks}
    gw_xloss = {w: so.expr_sum(merged_data.loc[p, f'{w}_xLoss'] * (1 - squad[p,w]) for p in players) for w in gameweeks}

    # Update the objective to subtract xloss for unselected players
    if objective == 'regular':
        gw_total = {w: gw_xp[w] + - 4 * penalized_transfers[w] + ft_value * free_transfers[w] + itb_value * in_the_bank[w] for w in gameweeks}
    elif objective == 'relative': # objective is absolute/netgain
        gw_total = {w: gw_xgain[w] - gw_xloss[w] - 4 * penalized_transfers[w] + ft_value * free_transfers[w] + itb_value * in_the_bank[w] for w in gameweeks}

#     total_xp = so.expr_sum(gw_total[w] * pow(decay_base, w-next_gw) for w in gameweeks)
#     model.set_objective(-total_xp, sense='N', name='total_regular_xp')


    # OLD Version without subtracting unselected players
#     gw_xp = {w: so.expr_sum(points_player_week[p,w] * (lineup[p,w] + captain[p,w] + 0.1*vicecap[p,w] + so.expr_sum(bench_weights[o] * bench[p,w,o] for o in order)) for p in players) for w in gameweeks}
#     gw_total = {w: gw_xp[w] - 4 * penalized_transfers[w] + ft_value * free_transfers[w] + itb_value * in_the_bank[w] for w in gameweeks}
    # Attempt at netgain
    gw_ng = {w: so.expr_sum(ng_player_week[p,w] * (lineup[p,w] + captain[p,w] + 0.1*vicecap[p,w] + so.expr_sum(bench_weights[o] * bench[p,w,o] for o in order)) for p in players) for w in gameweeks}
    gw_ng_total = {w: gw_ng[w] - 4 * penalized_transfers[w] + ft_value * free_transfers[w] + itb_value * in_the_bank[w] for w in gameweeks}

    ### Additions
#     gw_xgain = {w: so.expr_sum(gain_player_week[p,w] * (lineup[p,w] + captain[p,w] + 0.1*vicecap[p,w] + so.expr_sum(bench_weights[o] * bench[p,w,o] for o in order)) for p in players) for w in gameweeks}
#     gw_total_xgain = {w: gw_xgain[w] - 4 * penalized_transfers[w] + ft_value * free_transfers[w] + itb_value * in_the_bank[w] for w in gameweeks}

    total_xp = so.expr_sum(gw_total[w] * pow(decay_base, w-next_gw) for w in gameweeks)
    model.set_objective(-total_xp, sense='N', name=f'total_{objective}_xp')


#     if objective == 'regular':
#         total_xp = so.expr_sum(gw_total[w] * pow(decay_base, w-next_gw) for w in gameweeks)
#         model.set_objective(-total_xp, sense='N', name='total_regular_xp')
# #         total_xgain = so.expr_sum(gw_total_xgain[w] for w in gameweeks)
# #         model.set_objective(-total_xgain, sense='N', name='total_regular_xgain')
#     elif objective == 'absolute':
#         total_xng = so.expr_sum(gw_ng_total[w] for w in gameweeks)
#         model.set_objective(-total_xng, sense='N', name='total_ng')
#     # not used
#     else:
#         decay_objective = so.expr_sum(gw_total[w] * pow(decay_base, w-next_gw) for w in gameweeks)
#         model.set_objective(-decay_objective, sense='N', name='total_decay_xp')

    # Solve
    tmp_folder = Path() / "tmp"
    tmp_folder.mkdir(exist_ok=True, parents=True)
    model.export_mps(f'tmp/{problem_name}_{problem_id}.mps')
    print(f"Exported problem with name: {problem_name}_{problem_id}")

    t0 = time.time()
    time.sleep(0.5)

    if options.get('export_debug', False) is True:
        with open("debug.sas", "w") as file:
            file.write(model.to_optmodel())
#     export_debug = False
#     if export_debug is True:
#         with open("debug.sas", "w") as file:
#             file.write(model.to_optmodel())

    use_cmd = options.get('use_cmd', False)
#     use_cmd = True

    solver = options.get('solver', 'cbc')
#     solver = 'cbc'

    if solver == 'cbc':

        command = f'cbc tmp/{problem_name}_{problem_id}.mps cost column ratio 1 solve solu tmp/{problem_name}_{problem_id}_sol_init.txt'

        if use_cmd:
            os.system(command)
        else:
            process = Popen(command, shell=False)
            process.wait()

        secs = options.get('secs', 20*60)
#         secs = 20*60

        command = f'cbc tmp/{problem_name}_{problem_id}.mps mips tmp/{problem_name}_{problem_id}_sol_init.txt cost column sec {secs} solve solu tmp/{problem_name}_{problem_id}_sol.txt'

        if use_cmd:
            os.system(command)
        else:
            process = Popen(command, shell=False) # add 'stdout=DEVNULL' for disabling logs
            process.wait()

        # Popen fix with split?

        t1 = time.time()
        print(t1-t0, "seconds passed")

        # Parsing
        with open(f'tmp/{problem_name}_{problem_id}_sol.txt', 'r') as f:
            for line in f:
                if 'objective value' in line:
                    continue
                words = line.split()
                var = model.get_variable(words[1])
                var.set_value(float(words[2]))

    elif solver == 'highs':

        highs_exec = options.get('solver_path', 'highs')
#         highs_exec = 'highs'

        secs = options.get('secs', 20*60)
#         secs = 20*60

        command = f'{highs_exec} --presolve off --model_file tmp/{problem_name}_{problem_id}.mps --time_limit {secs} --solution_file tmp/{problem_name}_{problem_id}_sol.txt'
        if use_cmd:
            os.system(command)
        else:
            process = Popen(command, shell=False)
            process.wait()

        # Parsing
        with open(f'tmp/{problem_name}_{problem_id}_sol.txt', 'r') as f:

            cols_started = False

            for line in f:
                if not cols_started and "# Columns" not in line:
                    continue
                elif "# Columns" in line:
                    cols_started = True
                    continue
                elif cols_started and line[0] != "#":
                    words = line.split()
                    v = model.get_variable(words[0])
                    try:
                        if v.get_type() == so.INT:
                            v.set_value(round(float(words[1])))
                        elif v.get_type() == so.BIN:
                            v.set_value(round(float(words[1])))
                        elif v.get_type() == so.CONT:
                            v.set_value(round(float(words[1]),3))
                    except:
                        print("Error", words[0], line)
                elif line[0] == "#":
                    break


#     use_cmd = options.get('use_cmd', False)
    use_cmd = True

    # DataFrame generation
    picks = []
    for w in gameweeks:
        for p in players:
            if squad[p,w].get_value() + squad_fh[p,w].get_value() + transfer_out[p,w].get_value() > 0.5:
                lp = merged_data.loc[p]
                is_captain = 1 if captain[p,w].get_value() > 0.5 else 0
                is_squad = 1 if (use_fh[w].get_value() < 0.5 and squad[p,w].get_value() > 0.5) or (use_fh[w].get_value() > 0.5 and squad_fh[p,w].get_value() > 0.5) else 0
                is_lineup = 1 if lineup[p,w].get_value() > 0.5 else 0
                is_vice = 1 if vicecap[p,w].get_value() > 0.5 else 0
                is_transfer_in = 1 if transfer_in[p,w].get_value() > 0.5 else 0
                is_transfer_out = 1 if transfer_out[p,w].get_value() > 0.5 else 0
                bench_value = -1
                for o in order:
                    if bench[p,w,o].get_value() > 0.5:
                        bench_value = o
                position = type_data.loc[lp['element_type'], 'singular_name_short']
                player_buy_price = 0 if not is_transfer_in else buy_price[p]
                player_sell_price = 0 if not is_transfer_out else (sell_price[p] if p in price_modified_players and transfer_out_first[p,w].get_value() > 0.5 else buy_price[p])
                multiplier = 1*(is_lineup==1) + 1*(is_captain==1)
                xp_cont = points_player_week[p,w] * multiplier
                
                ### Additions for ownership
                xng_cont = ng_player_week[p,w] * multiplier
                curr_own = merged_data.loc[p, 'curr_own']
    #             xnet_gain = points_player_week[p,w] * multiplier * (1 - 2 * curr_own)

                picks.append([
                    w, lp['web_name'], position, lp['element_type'], lp['name'], player_buy_price, player_sell_price, round(points_player_week[p,w],2), round(wpoints_player_week[p,w],2), minutes_player_week[p,w], is_squad, is_lineup, bench_value, is_captain, is_vice, is_transfer_in, is_transfer_out, multiplier, xp_cont, curr_own, round(ng_player_week[p,w],2), xng_cont
                ])

    picks_df = pd.DataFrame(picks, columns=['week', 'name', 'pos', 'type', 'team', 'buy_price', 'sell_price', 'xP', 'wxP', 'xMin', 'squad', 'lineup', 'bench', 'captain', 'vicecaptain', 'transfer_in', 'transfer_out', 'multiplier', 'xp_cont', 'curr_own', 'xng', 'xng_cont']).sort_values(by=['week', 'lineup', 'type', 'xng'], ascending=[True, False, True, True])
    total_xp = so.expr_sum((lineup[p,w] + captain[p,w]) * points_player_week[p,w] for p in players for w in gameweeks).get_value()
    total_xng = so.expr_sum((lineup[p,w] + captain[p,w]) * ng_player_week[p,w] for p in players for w in gameweeks).get_value()

    picks_df.sort_values(by=['week', 'squad', 'lineup', 'bench', 'type'], ascending=[True, False, False, True, True], inplace=True)

    # Writing summary
    summary_of_actions = "\n"
    summary_of_actions += f"TOTAL xP = {total_xp} \n"
    summary_of_actions += f"TOTAL xNG = {total_xng} \n"
    for w in gameweeks:
        summary_of_actions += f"------------------- GW{w} -------------------\n"
        summary_of_actions += "CHIP = " + ("WC" if use_wc[w].get_value() > 0.5 else "") + ("FH" if use_fh[w].get_value() > 0.5 else "") + ("BB" if use_bb[w].get_value() > 0.5 else "None") + "\n"
        summary_of_actions += f"GW xP = {round(gw_total[w].get_value(),2)}, ITB = {in_the_bank[w].get_value()}, FT = {free_transfers[w].get_value()}, Hits = {penalized_transfers[w].get_value()} \n" # NT={number_of_transfers[w].get_value()}\n
        summary_of_actions += f"GW xNG = {round(gw_ng_total[w].get_value(),2)} \n\n" 
        for p in players:
            if transfer_in[p,w].get_value() > 0.5:
                summary_of_actions += f"Buy {p} - {merged_data['web_name'][p]}\n"
        for p in players:
            if transfer_out[p,w].get_value() > 0.5:
                summary_of_actions += f"Sell {p} - {merged_data['web_name'][p]}\n"

        lineup_players = picks_df[(picks_df['week'] == w) & (picks_df['lineup'] == 1)]
        bench_players = picks_df[(picks_df['week'] == w) & (picks_df['bench'] >= 0)]

        summary_of_actions += "\nLineup: " + ', '.join(lineup_players['name'].tolist()) + "\n"
        summary_of_actions += "Bench: " + ', '.join(bench_players['name'].tolist()) + "\n"
    #         summary_of_actions += "Lineup xPts: " + str(round(lineup_players['xp_cont'].sum(),2)) + "\n---\n\n"


    # if options.get('delete_tmp'):
    #     os.unlink(f"tmp/{problem_name}_{problem_id}.mps")
    #     os.unlink(f"tmp/{problem_name}_{problem_id}_sol.txt")
    delete_tmp = False
    if delete_tmp is True:
        os.unlink(f"tmp/{problem_name}_{problem_id}.mps")
        os.unlink(f"tmp/{problem_name}_{problem_id}_sol.txt")


    return {
        'model': model, 
        'picks': picks_df, 
        'total_xp': total_xp, 
        'total_xng': total_xng,
        'summary': summary_of_actions,
        'merged_data': merged_data
        }


if __name__ == '__main__':

    t0 = time.time()

    options = {
        'horizon': 3,
        'randomized': False,
        # 'seed': 42
        # 'use_wc': 8,
        'wc_limit': 0,
        'banned': [],
        'xmin_lb': 0
    }

    session, team_id = connect()
    my_data = get_my_data(session, team_id)
    data = prep_data(my_data, options)
    result = solve_multi_period_fpl(data, options)
    merged_data.to_csv('../data/merged_data.csv')

    final_time = time.time()
    print(final_time - t0, "seconds passed in total")

    # You can change "use_wc" to another GW if you haven't activated your WC
    if False:
        options['use_wc'] = 12
        data = prep_data(my_data, options)
        result = solve_multi_period_fpl(data, options)
        print(result['summary'])
        result['picks'].to_csv("gw12_wildcard.csv")


    # solve_standard_problem() # Episode 3 & 5
    # solve_autobench_problem() # Episode 6
    # solve_randomized_problem() # Episode 7