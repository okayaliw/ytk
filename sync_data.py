# sync_data.py

from datetime import date
from app import app, db, Channel, ChannelStats, fetch_channel_data_from_api

print("Data sync script started.")

def sync_all_channels():
    with app.app_context():
        try:
            channels_to_sync = Channel.query.all()
            if not channels_to_sync:
                print("No channels in the database to sync.")
                return

            print(f"Found {len(channels_to_sync)} channels to sync.")
            
            for channel in channels_to_sync:
                print(f"Syncing data for: {channel.name} ({channel.youtube_channel_id})")
                channel_data, error = fetch_channel_data_from_api(channel.youtube_channel_id)
                if error:
                    print(f"  > ERROR: Could not fetch data for {channel.name}. Reason: {error}")
                    continue

                today = date.today()
                existing_stat = ChannelStats.query.filter_by(channel_id=channel.id, date=today).first()

                if existing_stat:
                    print(f"  > INFO: Updating existing stat for {today}.")
                    existing_stat.subscriber_count = channel_data['subscriber_count']
                    existing_stat.view_count = channel_data['view_count']
                    existing_stat.video_count = channel_data['video_count']
                else:
                    print(f"  > INFO: Creating new stat for {today}.")
                    new_stat = ChannelStats(
                        channel_id=channel.id,
                        date=today,
                        subscriber_count=channel_data['subscriber_count'],
                        view_count=channel_data['view_count'],
                        video_count=channel_data['video_count']
                    )
                    db.session.add(new_stat)
                
                print(f"  > SUCCESS: Synced {channel_data['subscriber_count']} subs.")

            db.session.commit()
            print("All changes have been committed to the database.")
        except Exception as e:
            print(f"An unexpected error occurred during sync: {e}")
            db.session.rollback()
        finally:
            print("Data sync script finished.")

if __name__ == "__main__":
    sync_all_channels()