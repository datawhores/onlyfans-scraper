r"""
               _          __                                                                      
  ___   _ __  | | _   _  / _|  __ _  _ __   ___         ___   ___  _ __   __ _  _ __    ___  _ __ 
 / _ \ | '_ \ | || | | || |_  / _` || '_ \ / __| _____ / __| / __|| '__| / _` || '_ \  / _ \| '__|
| (_) || | | || || |_| ||  _|| (_| || | | |\__ \|_____|\__ \| (__ | |   | (_| || |_) ||  __/| |   
 \___/ |_| |_||_| \__, ||_|   \__,_||_| |_||___/       |___/ \___||_|    \__,_|| .__/  \___||_|   
                  |___/                                                        |_|                
"""

import argparse
import asyncio
import datetime
import os
import sys
import platform
from random import randint, choice
from time import sleep
import time
from datetime import datetime, timedelta
import schedule
from contextlib import contextmanager
import threading
import queue
import functools
from itertools import chain
import re

from .constants import donateEP
from .api import init, highlights, me, messages, posts, profile, subscriptions, paid
from .db import operations
from .interaction import like
from .utils import auth, config, download, profiles, prompts
import webbrowser
from revolution import Revolution
from .utils.nap import nap_or_sleep




# @need_revolution("Getting messages...")
@Revolution(desc='Getting messages...')
def process_messages(headers, model_id):
    messages_ = messages.scrape_messages(headers, model_id)
    output=[]
    if messages_:
        [output.extend(messages.parse_messages([ele],model_id)) for ele in messages_]       
    return output

# @need_revolution("Getting highlights...")
@Revolution(desc='Getting highlights...')
def process_highlights(headers, model_id):
    highlights_, stories = highlights.scrape_highlights(headers, model_id)

    if highlights_ or stories:
        highlights_ids = highlights.parse_highlights(highlights_)
        stories += asyncio.run(
            highlights.process_highlights_ids(headers, highlights_ids))
        stories_urls = highlights.parse_stories(stories)
        return stories_urls
    return []

# @need_revolution("Getting subscriptions...")
@Revolution(desc='Getting archived media...')
def process_archived_posts(headers, model_id):
    archived_posts = posts.scrape_archived_posts(headers, model_id)
    if archived_posts:
        archived_posts_urls = posts.parse_posts(archived_posts)
        return archived_posts_urls
    return []

# @need_revolution("Getting timeline media...")
@Revolution(desc='Getting timeline media...')
def process_timeline_posts(headers, model_id):
    timeline_posts = posts.scrape_timeline_posts(headers, model_id)
    if timeline_posts:
        timeline_posts_urls = posts.parse_posts(timeline_posts)
        return timeline_posts_urls
    return []


# @need_revolution("Getting pinned media...")
@Revolution(desc='Getting pinned media...')
def process_pinned_posts(headers, model_id):
    pinned_posts = posts.scrape_pinned_posts(headers, model_id)
    if pinned_posts:
        pinned_posts_urls = posts.parse_posts(pinned_posts)
        return pinned_posts_urls
    return []


def process_profile(headers, username) -> list:
    user_profile = profile.scrape_profile(headers, username)
    urls, info = profile.parse_profile(user_profile)
    profile.print_profile_info(info)
    return urls


def process_areas_all(headers, username, model_id) -> list:
    profile_tuple = process_profile(headers, username)

    pinned_posts_tuple = process_pinned_posts(headers, model_id)
    timeline_posts_tuple = process_timeline_posts(headers, model_id)
    archived_posts_tuple = process_archived_posts(headers, model_id)
    highlights_tuple= process_highlights(headers, model_id)
    messages_tuple = process_messages(headers, model_id)

    combined_urls = profile_tuple + pinned_posts_tuple + timeline_posts_tuple + \
        archived_posts_tuple + highlights_tuple + messages_tuple

    return combined_urls


def process_areas(headers, username, model_id,selected=None) -> list:
    result_areas_prompt = (selected or prompts.areas_prompt()[0]).capitalize()

    if result_areas_prompt=="All":
        combined_urls = process_areas_all(headers, username, model_id)

    else:
        pinned_posts_urls = []
        timeline_posts_urls = []
        archived_posts_urls = []
        highlights_urls = []
        messages_urls = []

        profile_urls = process_profile(headers, username)

        if result_areas_prompt=='Timeline':
            pinned_posts_urls = process_pinned_posts(headers, model_id)
            timeline_posts_urls = process_timeline_posts(headers, model_id)

        if  result_areas_prompt=='Archived':
            archived_posts_urls = process_archived_posts(headers, model_id)

        if result_areas_prompt=='Highlights':
            highlights_urls = process_highlights(headers, model_id)

        if result_areas_prompt=='Messages':
            messages_urls = process_messages(headers, model_id)

        combined_urls = profile_urls + pinned_posts_urls + timeline_posts_urls + \
            archived_posts_urls + highlights_urls + messages_urls

    return combined_urls




def do_database_migration(path, model_id):
    results = operations.read_foreign_database(path)
    operations.write_from_foreign_database(results, model_id)


def get_usernames(parsed_subscriptions: list) -> list:
    usernames = [sub[0] for sub in parsed_subscriptions]
    return usernames


def get_model(parsed_subscriptions: list) -> tuple:
    """
    Prints user's subscriptions to console and accepts input from user corresponding 
    to the model(s) whose content they would like to scrape.
    """
    return prompts.model_selector(parsed_subscriptions)

  
def get_model_inputsplit(commaString):
    def hyphenRange(hyphenString):
        x = [int(x) for x in hyphenString.split('-')]
        return range(x[0], x[-1]+1)
    return chain(*[hyphenRange(r) for r in list(filter(lambda x:x.isdigit(),re.split(',| ',commaString)))])


def get_models(headers, subscribe_count) -> list:
    """
    Get user's subscriptions in form of a list.
    """
    with Revolution(desc='Getting your subscriptions (this may take awhile)...') as _:
        list_subscriptions = asyncio.run(
            subscriptions.get_subscriptions(headers, subscribe_count))
        parsed_subscriptions = subscriptions.parse_subscriptions(
            list_subscriptions)
    return parsed_subscriptions


def process_me(headers):
    my_profile = me.scrape_user(headers)
    name, username, subscribe_count = me.parse_user(my_profile)
    me.print_user(name, username)
    return subscribe_count


def process_prompts():
    loop = process_prompts
    result_main_prompt = prompts.main_prompt()
    headers = auth.make_headers(auth.read_auth())
    #download
    if result_main_prompt == 0:
        process_post()

    elif result_main_prompt == 1:
        process_paid()

    # like a user's posts
    elif result_main_prompt == 2:
        process_like()
    # Unlike a user's posts
    elif result_main_prompt == 3:
        process_unlike()

    elif result_main_prompt == 4:
        # Migrate from old database
        path, username = prompts.database_prompt()
        model_id = profile.get_id(headers, username)
        do_database_migration(path, model_id)
     

    elif result_main_prompt == 5:
        # Edit `auth.json` file
        auth.edit_auth()
    
    elif result_main_prompt == 6:
        # Edit `config.json` file
        config.edit_config()

      
 
    elif result_main_prompt == 7:
        # Display  `Profiles` menu
        result_profiles_prompt = prompts.profiles_prompt()

        if result_profiles_prompt == 0:
            # Change profiles
            profiles.change_profile()

        elif result_profiles_prompt == 1:
            # Edit a profile
            profiles_ = profiles.get_profiles()

            old_profile_name = prompts.edit_profiles_prompt(profiles_)
            new_profile_name = prompts.new_name_edit_profiles_prompt(
                old_profile_name)

            profiles.edit_profile_name(old_profile_name, new_profile_name)

        elif result_profiles_prompt == 2:
            # Create a new profile
            profile_path = profiles.get_profile_path()
            profile_name = prompts.create_profiles_prompt()

            profiles.create_profile(profile_path, profile_name)

        elif result_profiles_prompt == 3:
            # Delete a profile
            profiles.delete_profile()

        elif result_profiles_prompt == 4:
            # View profiles
            profiles.print_profiles()
    if args.username and prompts.reset_username_prompt()==True:
        args.username=None
    loop()
def process_paid():
    profiles.print_current_profile()
    headers = auth.make_headers(auth.read_auth())
    init.print_sign_status(headers)
    # all_paid_content = paid.scrape_paid()
    # usernames=getselected_usernames()
    usernames=["aroomikimfree"]
    for username in usernames:

        try:
            model_id = profile.get_id(headers, username)
            # paid_content=paid.parse_paid(all_paid_content,model_id)
            paid_content=[('https://cdn2.onlyfans.com/files/6/6c/6c54a41f984df5deab7760c20eb7339f/2160x2880_d88051e076d0ceb7da7733d786e84081.jpg?Tag=2&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6XC9cL2NkbjIub25seWZhbnMuY29tXC9maWxlc1wvNlwvNmNcLzZjNTRhNDFmOTg0ZGY1ZGVhYjc3NjBjMjBlYjczMzlmXC8yMTYweDI4ODBfZDg4MDUxZTA3NmQwY2ViN2RhNzczM2Q3ODZlODQwODEuanBnP1RhZz0yIiwiQ29uZGl0aW9uIjp7IkRhdGVMZXNzVGhhbiI6eyJBV1M6RXBvY2hUaW1lIjoxNjc5NDk1ODY0fSwiSXBBZGRyZXNzIjp7IkFXUzpTb3VyY2VJcCI6IjIxMy4xNTIuMTYxLjIxOVwvMzIifX19XX0_&Signature=b8g0FUdedPpMIzi42EMSw7oCSjN74Dm6Q9nCr-q6MNTqmAPiRAcPJpg9wCIzK00b8kV3QzLD613PFYIVwLdK9nWhf1oiAlO~USIK~MbZzb~c2PO-rRHZWMRr2AmTJtPjQTXtTI0DYhHQG-MPCCi5Gg1O1h6O3-UZWx6ev7kS9qc-KmVArreqkZuWhkDJDs3hcsC~x5C8G3IakIrWaneFEckzpW4QfrsYv8hFSBqR-H1kmrPrJSSB1XV8f~Elj6ygZYHYemox7TRaZJT~dyOBb~a79T9XeSsv5ZFSwTaEzYAtEAnLSjKDsofg-RgGXxSMxsgZ5dMZ3UeRZztYVFbQsQ__&Key-Pair-Id=APKAUSX4CWPPATFK2DGD', '2023-02-04T23:28:41+00:00', 2764940809, 'photo', '😈Stranger Fuck😈 I ran into a stranger that recognizes me! I was so happy I decide to make his dream cum true 🤩 after sucking his cock I start to ride his huge cock and have it stretch out my tight little pussy!😲💦then I let him cum all over my tits🥵', 'post', 1), ('https://cdn2.onlyfans.com/files/f/f0/f0263fcaf2f554647353df78579855c9/0has86xo3frjzlct4atud_source.mp4?Tag=2&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6XC9cL2NkbjIub25seWZhbnMuY29tXC9maWxlc1wvZlwvZjBcL2YwMjYzZmNhZjJmNTU0NjQ3MzUzZGY3ODU3OTg1NWM5XC8waGFzODZ4bzNmcmp6bGN0NGF0dWRfc291cmNlLm1wND9UYWc9MiIsIkNvbmRpdGlvbiI6eyJEYXRlTGVzc1RoYW4iOnsiQVdTOkVwb2NoVGltZSI6MTY3OTQ5NTg2NH0sIklwQWRkcmVzcyI6eyJBV1M6U291cmNlSXAiOiIyMTMuMTUyLjE2MS4yMTlcLzMyIn19fV19&Signature=Q6qetS3ptL6uhmVzXpdM4MwoHLlXelYbvKnOQT-aDsysv9~ud9giEJHZ8QRdSakr38b-5Yko1XMSivLwTEm9n1uOZwBiSZwd89jUBVphkzIwawmsrPMER-piMywhccTFySaqR8wNk5lutA2zbIUzk7C2OFsLCxMGPkNlWmSkOLAFQud-R2DEj3qRK65ikMPRJCyXSGxfS9mFhkm9OInY~9HU8Is8vKtRpcTgOIlLG4KPLWqbdCh~xZXrFNRJOYQfP5AnHrRiTBES2HM9M9lDk~QtQQzDaLuhx~eRlG97cLhTP8qzCKbnlSM6QoBqoqfUl0ZmKGQeuUo~HMq-mSw~XQ__&Key-Pair-Id=APKAUSX4CWPPATFK2DGD', '2023-02-04T22:47:36+00:00', 2764909965, 'video', '😈Stranger Fuck😈 I ran into a stranger that recognizes me! I was so happy I decide to make his dream cum true 🤩 after sucking his cock I start to ride his huge cock and have it stretch out my tight little pussy!😲💦then I let him cum all over my tits🥵', 'post', 2), ('https://cdn2.onlyfans.com/files/8/89/89b80752b9f8bdc7aa9526e30582afb7/2160x2880_e3f7c320dd427c69b35cb8150268eb0b.jpg?Tag=2&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6XC9cL2NkbjIub25seWZhbnMuY29tXC9maWxlc1wvOFwvODlcLzg5YjgwNzUyYjlmOGJkYzdhYTk1MjZlMzA1ODJhZmI3XC8yMTYweDI4ODBfZTNmN2MzMjBkZDQyN2M2OWIzNWNiODE1MDI2OGViMGIuanBnP1RhZz0yIiwiQ29uZGl0aW9uIjp7IkRhdGVMZXNzVGhhbiI6eyJBV1M6RXBvY2hUaW1lIjoxNjc5NDk1ODY0fSwiSXBBZGRyZXNzIjp7IkFXUzpTb3VyY2VJcCI6IjIxMy4xNTIuMTYxLjIxOVwvMzIifX19XX0_&Signature=FRkeP0mX4czKm1vRXPdr3w3q7Xky9IrMf5D-QDYrSCi9fPAbB9mCwIGBCSnCKlDRYCYGO8bVHIFh1~WDIIrqYaRfXCH~MssLWell8wIncI~1kwWB9rm333M4Ve-5eBjASrib3qnsrnnWAq5-m9-p9te-YxA12kdmfxeSDDhEDdsrbueYZ53nhU7PB3WOXr9014lYUKrW5j-f8zrZbWJiVekDr4HHZg8lMtyr6oiBX7Tmdcb04Hd2CZnPt99pqwHC4Wk7zmkOZrJp6Cy4~Pn9sn-5M5kzOiYF0XyI1NRwZlpjVSYdzP8zdG9iRvTNDfe6-kSq27RANGx2WvhnoltZjg__&Key-Pair-Id=APKAUSX4CWPPATFK2DGD', '2023-02-04T17:03:00+00:00', 2764649496, 'photo', 'NEW B/G CLIP I gave a stranger a massage but the session took a naughty turn when I started teasing him for something in return 😚 I let him fuck me raw in multiple positions💦 He cummed inside me🥺 I hope i’m not pregnant!! \U0001fae3', 'post', 1), ('https://cdn2.onlyfans.com/files/2/22/227fb22e920ceb3882d319d7dfc7b420/0hary84oy6rijhkdg9gv3_source.mp4?Tag=2&Policy=eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6XC9cL2NkbjIub25seWZhbnMuY29tXC9maWxlc1wvMlwvMjJcLzIyN2ZiMjJlOTIwY2ViMzg4MmQzMTlkN2RmYzdiNDIwXC8waGFyeTg0b3k2cmlqaGtkZzlndjNfc291cmNlLm1wND9UYWc9MiIsIkNvbmRpdGlvbiI6eyJEYXRlTGVzc1RoYW4iOnsiQVdTOkVwb2NoVGltZSI6MTY3OTQ5NTg2NH0sIklwQWRkcmVzcyI6eyJBV1M6U291cmNlSXAiOiIyMTMuMTUyLjE2MS4yMTlcLzMyIn19fV19&Signature=EKujJ8kl-mys6W9Qz2BXp7e58MxIzjfQn~qKjlL-oSjCAyh49SRNKHW8m5CA80afasm9E97Zw-vu~0htglGISs6q13~69mqe32dXvdC0W1Y9z-I0yzOdB-xR5WKmI2TEIMbw~uNsfl4k9Zgp4YJLAlNmwVon1YnhR5Iiy84YsreG1lpWj3KAlk6UTpAaG0JZvYTCcPWw~wgyFSy89E28a71vDm3uuxybJsGEVSB0N6xMPXf~C-Gzxb49IRuapMKDzB~2UcQ2cOiDmeUegX-rSIeoOBQ-HF3QFPJaJXqi7mii6nI0j1gGJNobdntlLV57MoBIhbz0xp9OSUFgJJAL3Q__&Key-Pair-Id=APKAUSX4CWPPATFK2DGD', '2023-02-04T17:03:00+00:00', 2764649497, 'video', 'NEW B/G CLIP I gave a stranger a massage but the session took a naughty turn when I started teasing him for something in return 😚 I let him fuck me raw in multiple positions💦 He cummed inside me🥺 I hope i’m not pregnant!! \U0001fae3', 'post', 2)]
            profile.print_paid_info(paid_content,username)
            asyncio.run(paid.process_dicts(
            headers,
            username,
            model_id,
            paid_content,
            forced=args.dupe
            ))
        except Exception as e:
            print("run failed with exception: ", e)


def process_post():
    profiles.print_current_profile()
    headers = auth.make_headers(auth.read_auth())
    init.print_sign_status(headers)
    usernames=getselected_usernames()
    for username in usernames:
        try:
            model_id = profile.get_id(headers, username)
            combined_urls=process_areas(headers, username, model_id,selected=args.posts)
            asyncio.run(download.process_dicts(
            headers,
            username,
            model_id,
            combined_urls,
            forced=args.dupe
            ))
        except Exception as e:
            print("run failed with exception: ", e)
    

def process_like():
    profiles.print_current_profile()
    headers = auth.make_headers(auth.read_auth())
    init.print_sign_status(headers)
    usernames=getselected_usernames()
    for username in usernames:
            model_id = profile.get_id(headers, username)
            posts = like.get_posts(headers, model_id)
            unfavorited_posts = like.filter_for_unfavorited(posts)
            post_ids = like.get_post_ids(unfavorited_posts)
            like.like(headers, model_id, username, post_ids)

def process_unlike():
    profiles.print_current_profile()
    headers = auth.make_headers(auth.read_auth())
    init.print_sign_status(headers)
    usernames=getselected_usernames()
    for username in usernames:
            model_id = profile.get_id(headers, username)
            posts = like.get_posts(headers, model_id)
            favorited_posts = like.filter_for_favorited(posts)
            post_ids = like.get_post_ids(favorited_posts)
            like.unlike(headers, model_id, username, post_ids)

@contextmanager
def suppress_stdout():
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        old_stderr=sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:  
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

def set_schedule(command,*params,**kwparams):
    schedule.every(args.daemon).minutes.do(jobqueue.put,functools.partial(command,*params,**kwparams))
    while True:
        schedule.run_pending()
        time.sleep(30)


## run script once or on schedule based on args
def run(command,*params,**kwparams):
    # get usernames prior to potentially supressing output
    getselected_usernames()
    print(f"starting script daemon:{args.daemon!=None} silent-mode:{args.silent}")    
    if args.silent:
        with suppress_stdout():
            run_helper(command,*params,**kwparams)
    else:
        run_helper(command,*params,**kwparams)
    print("script finished")

def run_helper(command,*params,**kwparams):   
    command(*params,**kwparams)
    if args.daemon:
        global jobqueue
        jobqueue=queue.Queue()
        worker_thread = threading.Thread(target=set_schedule,args=[command,*params],kwargs=kwparams)
        worker_thread.start()
        while True:
            job_func = jobqueue.get()
            job_func()
            jobqueue.task_done()
                
      
       

def getselected_usernames():
    #username list will be retrived once per run
    headers = auth.make_headers(auth.read_auth())
    if args.username and "!all" in args.username:
        subscribe_count = process_me(headers)
        parsed_subscriptions = get_models(headers, subscribe_count)
        args.username=get_usernames(parsed_subscriptions)
    
    #manually select usernames
    elif args.username==None:
        result_username_or_list_prompt = prompts.username_or_list_prompt()
        # Print a list of users:
        if result_username_or_list_prompt == 0:
            subscribe_count = process_me(headers)
            parsed_subscriptions = get_models(headers, subscribe_count)
            usernames= get_model(parsed_subscriptions)

            args.username=usernames
        elif result_username_or_list_prompt == 1:
            args.username=list(filter(lambda x:x!="",re.split(",| ",prompts.username_prompt())))
        #check if we should get all users
        elif prompts.verify_all_users_username_or_list_prompt():
            subscribe_count = process_me(headers)
            parsed_subscriptions = get_models(headers, subscribe_count)
            args.username=get_usernames(parsed_subscriptions)
    #remove dupes
    return list(set(args.username))







def main():
    global args
    if platform.system == 'Windows':
        os.system('color')
    # try:
    #     webbrowser.open(donateEP)
    # except:
    #     pass


    parser = argparse.ArgumentParser()
    #This needs to be global


    #share the args
    parser = argparse.ArgumentParser(add_help=False)                                         
    parser.add_argument(
        '-u', '--username', help="select which username to process (name,name2)\nSet to !all for all users",type=lambda x: list(filter( lambda y:y!="",x.split(",")))
    )
    parser.add_argument(
        '-d', '--daemon', help='run script in the background\nSet value to minimum minutes between script runs\nOverdue runs will run as soon as previous run finishes', type=int,default=None
    )
    parser.add_argument(
        '-s', '--silent', help = 'mute output', action = 'store_true',default=False
    )
    parser.add_argument("-e","--dupe",action="store_true",default=False,help="Bypass the dupe check and redownload all files")
    parser.add_argument(
        '-o', '--posts', help = 'Download content from a models wall',default=None,required=False,type = str.lower,choices=["highlights","all","archived","messages","timeline"]
    )
    parser.add_argument("-p","--purchased",action="store_true",default=False,help="Download individually purchased content")
    parser.add_argument("-a","--action",default=None,help="perform like or unlike action on each post",choices=["like","unlike"])

   
   
    args = parser.parse_args()
   
    if len(list(filter(lambda x:x!=None and x!=False,[args.action,args.purchased,args.posts])))==0:
        process_prompts()
        sys.exit(0)
    

   #process user selected option

    if args.posts: 
        run(process_post)        
    if args.purchased:
        run(process_paid)
    if args.action=="like":
        run(process_like)
    if args.action=="unlike":
        run(process_unlike)  


if __name__ == '__main__':
    main()
