# Original Author: Alexis Perrier <alexis.perrier@gmail.com>
# Modifications: Amy Xiao <amyxst@gmail.com>
# License: BSD 3 clause
# Python 3
'''
Gets data from Twitter.
Requires Twython and pymongo (and mongo Db running)
Python 3.4

Usage:
    Get follower IDs for an account that has 5000 followers
    python get_tweets.py --followers --screen_name berkleecollege --n_followers=5000

    Get timelines of followers (limit to 100 TLs):
    python get_tweets.py --timelines --screen_name berkleecollege --n_followers=100

    Get full timelines of followers limited to most recent 180 days:
    python get_tweets.py --timelines -a --screen_name berkleecollege --n_days=180

The script assumes the account name exists
'''

from __future__ import print_function
import logging
import numpy as np
import sys

from optparse import OptionParser
from configparser import ConfigParser
import time
from pymongo import MongoClient
from twython import Twython, TwythonRateLimitError
from dateutil import parser
import datetime as dt
from datetime import datetime

def is_recent(twt):
    '''Checks that the tweet is more recent than n_days'''
    return parser.parse(twt['created_at']).replace(tzinfo=None) > \
                    (dt.datetime.today() -  dt.timedelta(days=n_days))

def corpus_status(screen_name):
    ''' State of the stored corpus: number of documents, average length
        and number of tweets per Timeline'''

    print("\n-------- Corpus --------")
    timelines = db.tweets.find({'parent':screen_name})
    documents    = [tw['raw_text']  for tw in timelines]
    print("  We have " + str(len(documents)) + " documents ")
    timelines.rewind()
    n_tweets = sum([tw['n_tweets']  for tw in timelines
                    if 'n_tweets' in tw.keys() and tw['n_tweets'] >0 ])
    print()
    print("  Total number of tweets: ", n_tweets)
    print("  On average #tweets per document: %0.2f" %
                        (n_tweets / len(documents)))
    timelines.rewind()
    len_text = [tw['len_text']  for tw in timelines
                    if 'len_text' in tw.keys() and tw['len_text'] > 0]
    m_len_text = np.mean(len_text)
    print("  Text length: Mean: %0.2f    STD: %0.2f"
                        % (np.mean(len_text), np.std(len_text)) )
    print()
    timelines.rewind()
    above_avg = [tw for tw in timelines
                    if 'len_text' in tw.keys() and tw['len_text'] > m_len_text]
    print(" => %0.2f documents above average:  " % len(above_avg) )

def followers_status(screen_name):
    followers = db.followers.find_one({"screen_name": screen_name})
    print("We have %s follower IDs for %s" %
                (len(followers['ids']), screen_name))

def wait_for_awhile():
    reset = int(twitter.get_lastfunction_header('x-rate-limit-reset'))
    wait = max(reset - time.time(), 0) + 10
    print("Rate limit exceeded waiting: %sm %0.0fs"%
            (int(int( wait)/60),wait % 60 ))
    time.sleep(wait)

def getTimeline(all_tweets, **kwargs):
    id = kwargs["user_id"]
    params = kwargs
    timeline = list()
    failed = False

    while not failed:
        try:
            new_tweets = twitter.get_user_timeline(**params)
            timeline.extend(new_tweets)
            # print("timeline {}".format(timeline))

            if all_tweets:
                # print("here")
                # print(timeline[-1].keys())
                # print("testing {}".format(timeline[-1]["contributors"]))
                params['max_id'] = timeline[-1]["id"]-1

                while len(new_tweets) > 0 and not failed:
                    try:
                        new_tweets = twitter.get_user_timeline(**params)
                        timeline.extend(new_tweets)
                        params['max_id'] = timeline[-1]["id"]-1
                    except TwythonRateLimitError as e:
                        print("Timeline length: {}".format(len(timeline)))
                        print("Last tweet collected: {}".format(timeline[-1]))
                        corpus_status(screen_name)
                        wait_for_awhile()
                    except Exception as e:
                        failed = True
                        print(e.message)
            break
        except TwythonRateLimitError as e:
            print("First pass rate limit exceeded...")
            corpus_status(screen_name)
            wait_for_awhile()
        except Exception as e:
            failed = True
            print(" FAILED:", id)
            print(e.message)
            print("Unexpected error:", sys.exc_info()[0])
            failed = True

    return timeline, failed

print(__doc__)

# Display progress logs on stdout
logging.basicConfig(level=logging.INFO,
                    format='>>> %(asctime)s %(levelname)s %(message)s')

# ---------------------------------------------------------
#  parse commandline arguments
# ---------------------------------------------------------

op = OptionParser()
op.add_option("-s", "--screen_name",
              dest="screen_name", type="string",
              help="Screen name of the main account")

op.add_option("-f", "--followers",
              action="store_true", dest="followers", default=False,
              help="Extracts IDs of screen_name followers from Twitter")

op.add_option("-t", "--timelines",
              action="store_true", dest="timelines", default=False,
              help="Extracts timelines of the followers from Twitter")

op.add_option("-d", "--dbname", dest="dbname", default='twitter',
              help="Name of the MongoDB collection")

op.add_option("-n", "--n_followers", dest="n_followers", default='5000',
              help="Number of follower IDs; 5000 at a time")

op.add_option("-a", "--all_tweets", 
              action="store_true", dest="all_tweets", default=False,
              help="Number of Tweets to collect from timeline; 200 by default")

op.add_option("-r", "--n_days_recent", dest="n_days_recent", default='-1',
              help="Collect specified days of most recent Tweets; all by default")

# Initialize
(opts, args) = op.parse_args()
print(opts)
print(args)

screen_name  = opts.screen_name.lower()     # The main twitter account
n_followers  = int(opts.n_followers)
n_days       = int(opts.n_days_recent) if not opts.n_days_recent == "-1" else None # Only tweets more recent than n_days are kept

# ---------------------------------------------------------
#  Twitter Connection: credentials stored in twitter.cfg
# ---------------------------------------------------------
config = ConfigParser()
config.read('twitter.cfg')
# for py27 change config to get_config
APP_KEY       = config['credentials']['app_key']
APP_SECRET    = config['credentials']['app_secret']
twitter       = Twython(APP_KEY, APP_SECRET, oauth_version=2)
ACCESS_TOKEN  = twitter.obtain_access_token()
twitter       = Twython(APP_KEY, access_token=ACCESS_TOKEN)

#  MongoDB connection
client      = MongoClient()
db          = client[opts.dbname]

# -----------------------------------------------------------
#  Follower IDs
# -----------------------------------------------------------

if opts.followers:
    followers_query_size = min(n_followers,5000) # Twitter default
    print("Retrieving %s followers" % n_followers)
    # ------------------------------------------------------------------
    #  1) get follower ids
    #  see https://dev.twitter.com/rest/reference/get/followers/ids
    # ------------------------------------------------------------------

    # Initialize the database followers record for that screen_name
    res = db.followers.find_one( {"screen_name": screen_name})
    if res is None:
        db.followers.insert_one( {"screen_name": screen_name, "ids": []} )

    # cursor is used to navigate a twitter collection
    # https://dev.twitter.com/overview/api/cursoring
    next_cursor     = -1
    follower_ids    = list()
    ids_count       = 0
    while (next_cursor != 0) and ( ids_count < n_followers):
        try:
            print("Followers %s to %s: cursor: %s" %
                    (ids_count, ids_count + followers_query_size, next_cursor))
            result = twitter.get_followers_ids(screen_name = screen_name,
                                            count = followers_query_size,
                                            cursor = next_cursor)

            follower_ids = follower_ids + result['ids']
            next_cursor = result['next_cursor']
            ids_count += len(result['ids'])
            # make sure the list only has unique IDs and sort
            follower_ids = list(set(follower_ids))
            follower_ids.sort()
            print("Retrieved %s follower IDs from twitter" % len(follower_ids))
            # store what we've got so far
            # insert follower_ids in the followers collection
            res = db.followers.update_one(
                    {"screen_name": screen_name},
                    { '$set': {"ids": follower_ids} }
                )
            if res.matched_count == 0:
                print("Unable to update IDs for: ",screen_name)
            elif res.modified_count == 0:
                print("%s IDs not modified"% screen_name)
            else:
                print("%s now has %s IDs " %  (screen_name, str(len(follower_ids)))  )

            followers_status(screen_name)
        except TwythonRateLimitError as e:
            # Wait if we hit the Rate limit
            followers_status(screen_name)
            wait_for_awhile()
        except:
            print(" FAILED: Unexpected error:", sys.exc_info()[0])
            pass

    # followers_status(screen_name)


# -----------------------------------------------------------
#  Timelines
# -----------------------------------------------------------
if opts.timelines:
    # catch IDs that error out
    error_ids = list()

    followers = db.followers.find_one({"screen_name": screen_name})
    print("Retrieving timelines of %s followers" % len(followers['ids']))

    # Get all timelines or limited to n_followers
    if n_followers is None:
        follower_ids = followers['ids']
    else:
        follower_ids = followers['ids'][0:n_followers-1]

    for id in follower_ids:
        params = {'user_id': id, 'count': 200, 
                    'contributor_details': 'true'}
        
        timeline, failed = getTimeline(opts.all_tweets, **params)

        if failed:
            error_ids.append(id)

        else:
            try:
                print("{} entered".format(id))
                if n_days:
                    # keep only recent_tweets in specified day range
                    timeline = [twt for twt in timeline if is_recent(twt)]

                # Aggregate the tweets to create the document
                text = ' '.join( [tw['text'] for tw in timeline])

                item = {
                        'raw_text': text,
                        'user_id':  id,
                        'len_text': len(text),
                        'n_tweets': len(timeline),
                        'screen_name': timeline[0]['user']['screen_name'],
                        'lang': timeline[0]['lang'],
                        'parent': screen_name
                    }

                # do we already have this account in the db?
                twt = db.tweets.find({'user_id':id, 'parent': screen_name})

                # if we do, update the data else create a new entry
                if twt.count() == 0:
                    # store document
                    print("New account:",timeline[0]['user']['screen_name'],
                                        id,len(timeline), timeline[0]['lang'])
                    db.tweets.insert_one(item)
                else:
                    # update the existing account record
                    res = db.tweets.replace_one(
                                {'user_id':id, 'parent': screen_name}, item
                            )
                    # result of the update
                    if res.matched_count == 0:
                        print("no match for id: ",id)
                    elif res.modified_count == 0:
                        print("no modification for id: ",id)
                    else:
                        print("replaced ",timeline[0]['user']['screen_name'],
                                        id,len(timeline), timeline[0]['lang'] )
            except Exception as e:
                error_ids.append(id)
                print(" FAILED:", id)
                print(" ", e.message)
                print(" Unexpected error:", sys.exc_info()[0])
                pass

    # ---------------------------------------------------------
    #  check how many documents we now have in the Database
    # ---------------------------------------------------------
    print("The following IDs errored out:", str(error_ids))

    corpus_status(screen_name)
