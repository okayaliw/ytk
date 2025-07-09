# sync_data.py

import os
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from app import Settings, Channel, ChannelStats, fetch_channel_data_from_api, app
except ImportError:
    print("Could not import from app.py.")
    exit(1)

print("Data sync script started.")

# Doğrudan app.py'daki URI'yi kullan
DATABASE_URI = app.config['SQLALCHEMY_DATABASE_URI']
engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)
session = Session()

def sync_all_channels():
    try:
        settings = session.query(Settings).first()
        if not settings or not settings.youtube_api_key:
            print("API Key not found in the database. Exiting.")
            return

        # app.py'ın API anahtarını kullanabilmesi için bir context oluştur
        with app.app_context():
            channels_to_sync = session.query(Channel).all()
            print(f"Found {len(channels_to_sync)} channels to sync.")
            for channel in channels_to_sync:
                # ... (Veri çekme ve veritabanına yazma mantığı AYNI kalacak) ...
    except Exception as e:
        # ... (Hata yönetimi AYNI kalacak) ...
    finally:
        session.close()

if __name__ == "__main__":
    sync_all_channels()