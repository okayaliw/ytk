# sync_data.py

import os
import requests
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Veritabanı modellerini ve yardımcı fonksiyonları app.py'dan import et
# Bu, kod tekrarını önler ve tek bir yerden yönetmemizi sağlar
try:
    from app import Settings, Channel, ChannelStats, fetch_channel_data_from_api
except ImportError:
    print("Could not import from app.py. Make sure this script is in the same directory.")
    exit(1)

print("Data sync script started.")

# Ortam değişkenlerini yükle (.env dosyasından veya GitHub secrets'tan)
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
API_KEY = os.getenv('YOUTUBE_API_KEY') # API Anahtarını da secret'tan alacağız

if not DATABASE_URL or not API_KEY:
    print("FATAL: DATABASE_URL and/or YOUTUBE_API_KEY environment variables not set.")
    exit(1)

# Veritabanı bağlantısı kur
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

def sync_all_channels():
    """Tüm kanalların verilerini çeker ve veritabanına kaydeder."""
    try:
        print("Fetching all channels from the database...")
        channels_to_sync = session.query(Channel).all()
        print(f"Found {len(channels_to_sync)} channels to sync.")

        for channel in channels_to_sync:
            print(f"Syncing data for: {channel.name} ({channel.youtube_channel_id})")
            
            # API'den veri çekme fonksiyonunu doğrudan çağırmak yerine,
            # API anahtarını parametre olarak alan bir versiyonunu oluşturalım
            # Bu, test edilebilirliği artırır ve daha temiz bir yaklaşımdır.
            # Şimdilik mevcut yapıyı kullanalım. fetch_channel_data_from_api global API anahtarını kullanacak.
            
            # Global API anahtarını güncelle
            # Bu geçici bir çözüm, daha iyi bir yapı için dependency injection gerekir.
            # Şimdilik işimizi görecektir.
            temp_app_context_for_api_key(API_KEY)

            channel_data, error = fetch_channel_data_from_api(channel.youtube_channel_id)
            
            if error:
                print(f"  > ERROR: Could not fetch data for {channel.name}. Reason: {error}")
                continue

            # Aynı gün için zaten kayıt var mı kontrol et
            today = date.today()
            existing_stat = session.query(ChannelStats).filter_by(channel_id=channel.id, date=today).first()

            if existing_stat:
                # Eğer kayıt varsa, güncelle
                print(f"  > INFO: Stat for {today} already exists. Updating it.")
                existing_stat.subscriber_count = channel_data['subscriber_count']
                existing_stat.view_count = channel_data['view_count']
                existing_stat.video_count = channel_data['video_count']
            else:
                # Eğer kayıt yoksa, yeni oluştur
                print(f"  > INFO: No stat for {today}. Creating a new one.")
                new_stat = ChannelStats(
                    channel_id=channel.id,
                    date=today,
                    subscriber_count=channel_data['subscriber_count'],
                    view_count=channel_data['view_count'],
                    video_count=channel_data['video_count']
                )
                session.add(new_stat)
            
            print(f"  > SUCCESS: Synced {channel_data['subscriber_count']} subscribers.")

        session.commit()
        print("All changes have been committed to the database.")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        session.rollback()
    finally:
        session.close()
        print("Database session closed.")

def temp_app_context_for_api_key(api_key):
    """
    app.py içindeki get_api_key() fonksiyonunun çalışabilmesi için
    geçici bir Flask app context'i oluşturur ve API anahtarını veritabanına yazar gibi yapar.
    Bu, app.py'ı değiştirmeden sync script'ini çalıştırmanın bir yoludur.
    """
    from app import app, db, Settings
    with app.app_context():
        settings = db.session.query(Settings).first()
        if not settings:
            settings = Settings()
            db.session.add(settings)
        settings.youtube_api_key = api_key
        db.session.commit()


if __name__ == "__main__":
    # Bu scripti çalıştırdığımızda API anahtarını veritabanından değil,
    # doğrudan GitHub Secrets'tan alacağız.
    # Bu yüzden `get_api_key_from_db` fonksiyonuna gerek kalmadı.
    sync_all_channels()