# sync_data.py

import os
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from app import app, Settings, Channel, ChannelStats, fetch_channel_data_from_api
except ImportError as e:
    print(f"Could not import from app.py: {e}")
    exit(1)

print("Data sync script started.")

DATABASE_URI = app.config['SQLALCHEMY_DATABASE_URI']
engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)
session = Session()

def sync_all_channels():
    with app.app_context():
        try:
            settings = session.query(Settings).first()
            if not settings or not settings.youtube_api_key:
                print("API Key not found in the database. Exiting.")
                return

            channels_to_sync = session.query(Channel).all()
            print(f"Found {len(channels_to_sync)} channels to sync.")
            
            for channel in channels_to_sync:
                print(f"Syncing data for: {channel.name} ({channel.youtube_channel_id})")
                channel_data, error = fetch_channel_data_from_api(channel.youtube_channel_id)
                if error:
                    print(f"  > ERROR: Could not fetch data. Reason: {error}")
                    continue

                today = date.today()
                existing_stat = session.query(ChannelStats).filter_by(channel_id=channel.id, date=today).first()

                if existing_stat:
                    print(f"  > INFO: Updating existing stat for {today}.")
                    existing_stat.subscriber_count = channel_data['subscriber_count']
                    existing_stat.view_count = channel_data['view_count']
                    existing_stat.video_count = channel_data['video_count']
                else:
                    print(f"  > INFO: Creating new stat for {today}.")
                    new_stat = ChannelStats(
                        channel_id=channel.id, date=today,
                        subscriber_count=channel_data['subscriber_count'],
                        view_count=channel_data['view_count'],
                        video_count=channel_data['video_count']
                    )
                    session.add(new_stat)
                
                print(f"  > SUCCESS: Synced {channel_data['subscriber_count']} subs.")

            session.commit()
            print("All changes have been committed.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            session.rollback()
        finally:
            session.close()
            print("Database session closed.")

if __name__ == "__main__":
    sync_all_channels()