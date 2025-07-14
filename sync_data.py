# sync_data.py

import os
import requests
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import Channel, ChannelStats, Settings, YOUTUBE_API_URL

# Veritabanı bağlantısını doğrudan kur
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
DATABASE_URI = 'sqlite:///' + os.path.join(instance_path, 'app.db')

engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)
session = Session()

def get_api_key_sync():
    settings = session.query(Settings).first()
    return settings.youtube_api_key if settings else None

def fetch_channel_data_from_api_sync(youtube_channel_id):
    api_key = get_api_key_sync()
    if not api_key: return None, "API Key not set."
    params = {'part': 'snippet,statistics,contentDetails', 'id': youtube_channel_id, 'key': api_key}
    response = requests.get(f"{YOUTUBE_API_URL}channels", params=params)
    if response.status_code != 200: return None, f"API request failed (status: {response.status_code})."
    data = response.json()
    if not data.get('items'): return None, "Channel not found on YouTube."
    item = data['items'][0]
    stats = item.get('statistics', {})
    return {'subscriber_count': int(stats.get('subscriberCount', 0)), 'view_count': int(stats.get('viewCount', 0)), 'video_count': int(stats.get('videoCount', 0))}, None


def sync_all_channels():
    print("Data sync script started.")
    try:
        if not get_api_key_sync():
            print("API Key not found in the database. Exiting.")
            return

        channels_to_sync = session.query(Channel).all()
        print(f"Found {len(channels_to_sync)} channels to sync.")
            
        for channel in channels_to_sync:
            print(f"Syncing data for: {channel.name} ({channel.youtube_channel_id})")
            channel_data, error = fetch_channel_data_from_api_sync(channel.youtube_channel_id)
            if error:
                print(f"  > ERROR: {error}")
                continue

            today = date.today()
            existing_stat = session.query(ChannelStats).filter_by(channel_id=channel.id, date=today).first()
            if existing_stat:
                existing_stat.subscriber_count = channel_data['subscriber_count']
                existing_stat.view_count = channel_data['view_count']
                existing_stat.video_count = channel_data['video_count']
            else:
                new_stat = ChannelStats(channel_id=channel.id, date=today, **channel_data)
                session.add(new_stat)
            print(f"  > SUCCESS: Synced {channel_data['subscriber_count']} subs.")

        session.commit()
        print("All changes have been committed to the database.")
    except Exception as e:
        print(f"An unexpected error occurred during sync: {e}")
        session.rollback()
    finally:
        session.close()
        print("Data sync script finished.")

if __name__ == "__main__":
    sync_all_channels()