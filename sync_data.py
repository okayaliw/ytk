# sync_data.py

import os
import requests
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Veritabanı modellerini app.py'dan import ediyoruz
from app import Channel, ChannelStats, Settings, get_api_key, fetch_channel_data_from_api

print("Data sync script started.")

# Ortam değişkenlerini yükle (.env dosyasından veya GitHub secrets'tan)
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    raise Exception("DATABASE_URL environment variable not set.")

# Veritabanı bağlantısı kur
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

def sync_all_channels():
    """Tüm kanalların verilerini çeker ve veritabanına kaydeder."""
    try:
        api_key = get_api_key_from_db() # API anahtarını da veritabanından alıyoruz
        if not api_key:
            print("API Key not found in the database. Exiting.")
            return

        print("Fetching all channels from the database...")
        channels_to_sync = session.query(Channel).all()
        print(f"Found {len(channels_to_sync)} channels to sync.")

        for channel in channels_to_sync:
            print(f"Syncing data for: {channel.name} ({channel.youtube_channel_id})")
            
            # YouTube API'den en son verileri çek
            # Not: fetch_channel_data_from_api'nin API anahtarını global yerine parametre alması daha iyi olur, ama şimdilik böyle çalışır.
            channel_data, error = fetch_channel_data_from_api(channel.youtube_channel_id)
            
            if error:
                print(f"  > ERROR: Could not fetch data for {channel.name}. Reason: {error}")
                continue

            # Yeni bir istatistik kaydı oluştur
            new_stat = ChannelStats(
                channel_id=channel.id,
                date=date.today(),
                subscriber_count=channel_data['subscriber_count'],
                view_count=channel_data['view_count'],
                video_count=channel_data['video_count']
            )
            session.add(new_stat)
            print(f"  > SUCCESS: Fetched {channel_data['subscriber_count']} subscribers.")

        # Tüm değişiklikleri veritabanına işle
        session.commit()
        print("All changes have been committed to the database.")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        session.rollback()
    finally:
        session.close()
        print("Database session closed.")

def get_api_key_from_db():
    """Zamanlayıcı script'inin API anahtarını veritabanından okumasını sağlar."""
    settings = session.query(Settings).first()
    return settings.youtube_api_key if settings else None


if __name__ == "__main__":
    sync_all_channels()