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
    result_areas_prompt = (selected or prompts.areas_prompt()).capitalize()

    if 'All' in result_areas_prompt:
        combined_urls = process_areas_all(headers, username, model_id)

    else:
        pinned_posts_urls = []
        timeline_posts_urls = []
        archived_posts_urls = []
        highlights_urls = []
        messages_urls = []

        profile_urls = process_profile(headers, username)

        if 'Timeline' in result_areas_prompt:
            pinned_posts_urls = process_pinned_posts(headers, model_id)
            timeline_posts_urls = process_timeline_posts(headers, model_id)

        if 'Archived' in result_areas_prompt:
            archived_posts_urls = process_archived_posts(headers, model_id)

        if 'Highlights' in result_areas_prompt:
            highlights_urls = process_highlights(headers, model_id)

        if 'Messages' in result_areas_prompt:
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
    to the model whose content they would like to scrape.
    """
    subscriptions.print_subscriptions(parsed_subscriptions)

    print('\nEnter the number next to the user whose content you would like to download:')
    while True:
        try:
            num = int(input('> '))
            return parsed_subscriptions[num - 1]
        except ValueError:
            print("Incorrect value. Please enter an actual number.")
        except IndexError:
            print("Value out of range. Please pick a number that's in range")


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
    # like a user's posts
    elif result_main_prompt == 1:
        usernames=getselected_usernames(headers)
        for username in usernames:
            model_id = profile.get_id(headers, username)
            posts = like.get_posts(headers, model_id)
            unfavorited_posts = like.filter_for_unfavorited(posts)
            post_ids = like.get_post_ids(unfavorited_posts)
            like.like(headers, model_id, username, post_ids)
    # Unlike a user's posts
    elif result_main_prompt == 2:
        usernames=getselected_usernames(headers)
        for username in usernames:
            model_id = profile.get_id(headers, username)
            posts = like.get_posts(headers, model_id)
            favorited_posts = like.filter_for_favorited(posts)
            post_ids = like.get_post_ids(favorited_posts)
            like.unlike(headers, model_id, username, post_ids)
    #need to fix 
    elif result_main_prompt == 3:
        # Migrate from old database
        path, username = prompts.database_prompt()
        model_id = profile.get_id(headers, username)
        do_database_migration(path, model_id)
        loop()

    elif result_main_prompt == 4:
        # Edit `auth.json` file
        auth.edit_auth()

        loop()

    elif result_main_prompt == 5:
        # Edit `config.json` file
        config.edit_config()

        loop()
    elif result_main_prompt == 6:
        process_paid()

    elif result_main_prompt == 7:
        # Display  `Profiles` menu
        result_profiles_prompt = prompts.profiles_prompt()

        if result_profiles_prompt == 0:
            # Change profiles
            profiles.change_profile()

        if result_profiles_prompt == 1:
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

        loop()
def process_paid():
    profiles.print_current_profile()
    headers = auth.make_headers(auth.read_auth())
    init.print_sign_status(headers)
    all_paid_content = paid.scrape_paid()
    usernames=getselected_usernames()
    for username in usernames:
        try:
            model_id = profile.get_id(headers, username)
            paid_content=paid.parse_paid(all_paid_content,model_id)
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
    usernames=getselected_usernames(headers)
    for username in usernames:
        try:
            model_id = profile.get_id(headers, username)
            combined_urls=process_areas(headers, username, model_id,selected=args.type)
            asyncio.run(download.process_dicts(
            headers,
            username,
            model_id,
            combined_urls,
            forced=args.dupe
            ))
        except Exception as e:
            print("run failed with exception: ", e)
    if args.paid:
        all_paid_content = paid.scrape_paid()
        for username in usernames:
            model_id = profile.get_id(headers, username)
            paid_content=paid.parse_paid(all_paid_content,model_id)
            paid.download_paid(paid_content,username,args.dupe)
            




@contextmanager
def suppress_stdout():
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:  
            yield
        finally:
            sys.stdout = old_stdout

def set_schedule(command,*params,**kwparams):
    schedule.every(10).seconds.do(jobqueue.put,functools.partial(command,*params,**kwparams))
    while True:
        schedule.run_pending()
        time.sleep(30)


## run script once or on schedule based on args
def run(command,*params,**kwparams):
    # run at least once
    command(*params,**kwparams)
    if args.daemon:
        print("starting daemon")    
        global jobqueue
        jobqueue=queue.Queue()
        worker_thread = threading.Thread(target=set_schedule,args=[command,*params],kwargs=kwparams)
        worker_thread.start()
        while True:
            job_func = jobqueue.get()
            job_func()
            jobqueue.task_done()
                
      
       

def getselected_usernames():
    headers = auth.make_headers(auth.read_auth())
    if args.username:
        None

    elif args.all:
        subscribe_count = process_me(headers)
        parsed_subscriptions = get_models(headers, subscribe_count)
        args.username=[get_usernames(parsed_subscriptions)]
 
    #manually select usernames
    else:
        result_username_or_list_prompt = prompts.username_or_list_prompt()
        # Print a list of users:
        if result_username_or_list_prompt == 0:
            subscribe_count = process_me(headers)
            parsed_subscriptions = get_models(headers, subscribe_count)
            username, *_ = get_model(parsed_subscriptions)
            args.username=[username]
        elif result_username_or_list_prompt == 1:
            args.username=[prompts.username_prompt()]
        #check if we should get all users
        elif prompts.verify_all_users_username_or_list_prompt():
            subscribe_count = process_me(headers)
            parsed_subscriptions = get_models(headers, subscribe_count)
            args.username=[get_usernames(parsed_subscriptions)]
    return args.username







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
    parent_parser = argparse.ArgumentParser(add_help=False)                                         
    parent_parser.add_argument(
        '-u', '--username', help="Download content from a user or list of users (name,name2)",type=lambda x: x.strip().split(',')
    )

    parent_parser.add_argument(
        '-a', '--all', help='scrape the content of all users', action='store_true')
    parent_parser.add_argument(
        '-d', '--daemon', help='This will run the program in the background and scrape everything from everyone. It will run untill manually killed.', action='store_true'
    )
    parent_parser.add_argument(
        '-s', '--silent', help = 'Run in silent mode', action = 'store_true',default=False
    )
    parent_parser.add_argument("-e","--dupe",action="store_true",default=False,help="download previously downloaded")
    subparsers = parser.add_subparsers(help='select which mode you want to run',dest="command",required=True)
    post = subparsers.add_parser('posts', help='scrape content from posts',parents=[parent_parser])
    post.add_argument(
        '-t', '--type', help = 'which type of posts to scrape',default=None,required=False,type = str.lower,choices=["highlights","all","archived","messages","timeline"]
    )
    post.add_argument("-p","--paid",action="store_true",default=False,help="download paid post")

    
  
    paid= subparsers.add_parser('paid', help='scrape only paid content',parents=[parent_parser])
    likes = subparsers.add_parser('like', help='manipulate likes',parents=[parent_parser])
    likes.add_argument("-t","--action",help="what batch action to take",type = str.lower,choices=["like","unlike"],required=True)
    edit = subparsers.add_parser('edit', help='edit',parents=[parent_parser])
    manual = subparsers.add_parser('manual', help='do stuff with prompts',parents=[parent_parser])



 



    args = parser.parse_args()
    if args.command=="edit":
        pass
    elif args.command=="posts":
        
        usernames=getselected_usernames(args)
        process_post(args,usernames)   
    elif args.command=="paid":
        run(process_paid)
    elif args.command=="likes":
        pass
        sys.exit()
    elif args.command=="manual":
        try:
            process_prompts(args)
        except KeyboardInterrupt:
            sys.exit(1)


if __name__ == '__main__':
    main()
