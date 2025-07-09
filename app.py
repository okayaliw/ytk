# app.py

import os
import requests
import csv
from io import StringIO
from datetime import date, datetime, timedelta
from flask import Flask, jsonify, render_template, request, abort, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, func

# --- 1. Yapılandırma ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-default-secret-key-for-local-dev'

# SQLite veritabanı yapılandırmasına geri dönüyoruz.
# Bu, projenin kendi içinde bir veritabanı dosyası kullanmasını sağlar.
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
os.makedirs(instance_path, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_path, 'app.db')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/"

# --- 2. Veritabanı Modelleri ---
# Settings modeli artık API anahtarını doğrudan veritabanında tutacak
class Settings(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True, default=1)
    youtube_api_key = db.Column(db.String(100), nullable=True)

class Channel(db.Model):
    __tablename__ = 'channels'
    id = db.Column(db.Integer, primary_key=True)
    youtube_channel_id = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    image_url = db.Column(db.String(255), nullable=False)
    uploads_playlist_id = db.Column(db.String(40), nullable=True)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    stats = db.relationship('ChannelStats', backref='channel', lazy=True, cascade="all, delete-orphan")

class ChannelStats(db.Model):
    __tablename__ = 'channel_stats'
    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channels.id', ondelete='CASCADE'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    subscriber_count = db.Column(db.Integer, nullable=False)
    view_count = db.Column(db.BigInteger, nullable=False)
    video_count = db.Column(db.Integer, nullable=False)

# --- 3. Veritabanı ve İlk Kurulum ---
@app.before_request
def initial_setup():
    # Bu fonksiyon, uygulama her çalıştığında veritabanı ve tabloların var olduğundan emin olur.
    with app.app_context():
        db.create_all()
        if Settings.query.first() is None:
            db.session.add(Settings(youtube_api_key=None))
            db.session.commit()

# --- 4. Yardımcı Fonksiyonlar ---
def get_api_key():
    # API anahtarını doğrudan veritabanından okur.
    settings = Settings.query.first()
    return settings.youtube_api_key if settings else None

def find_channel_id_from_query(query):
    api_key = get_api_key()
    if not api_key: return None, "API Key not set."
    if query.startswith('UC') and len(query) == 24:
        params = {'part': 'id', 'id': query, 'key': api_key}
        response = requests.get(f"{YOUTUBE_API_URL}channels", params=params)
        if response.ok and response.json().get('items'): return query, None
    params = {'part': 'snippet', 'q': query, 'type': 'channel', 'maxResults': 1, 'key': api_key}
    response = requests.get(f"{YOUTUBE_API_URL}search", params=params)
    data = response.json()
    if not data.get('items'): return None, f"No channel found for '{query}'."
    return data['items'][0]['id']['channelId'], None

def fetch_channel_data_from_api(youtube_channel_id):
    api_key = get_api_key()
    if not api_key: return None, "API key not set."
    params = {'part': 'snippet,statistics,contentDetails', 'id': youtube_channel_id, 'key': api_key}
    response = requests.get(f"{YOUTUBE_API_URL}channels", params=params)
    if response.status_code != 200: return None, f"API request failed (status: {response.status_code})."
    data = response.json()
    if not data.get('items'): return None, "Channel not found on YouTube."
    item = data['items'][0]
    snippet, stats, content_details = item['snippet'], item.get('statistics', {}), item.get('contentDetails', {})
    uploads_playlist_id = content_details.get('relatedPlaylists', {}).get('uploads')
    return {
        'name': snippet['title'], 'image_url': snippet['thumbnails']['default']['url'],
        'uploads_playlist_id': uploads_playlist_id,
        'subscriber_count': int(stats.get('subscriberCount', 0)),
        'view_count': int(stats.get('viewCount', 0)), 'video_count': int(stats.get('videoCount', 0)),
    }, None

# --- 5. Rotalar ---
@app.before_request
def check_api_key_redirect():
    if request.endpoint and request.endpoint not in ['settings', 'static']:
        if not get_api_key():
            flash('Please enter your YouTube API key to continue.', 'warning')
            return redirect(url_for('settings'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/channel/<int:id>')
def channel_detail(id):
    channel = Channel.query.get_or_404(id)
    return render_template('channel_detail.html', channel=channel)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    app_settings = Settings.query.first()
    if request.method == 'POST':
        app_settings.youtube_api_key = request.form.get('api_key')
        db.session.commit()
        flash('API key saved successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('settings.html', current_key=app_settings.youtube_api_key)

# --- 6. API Rotaları ---
def get_summary_and_channels_data():
    channels_db = Channel.query.all()
    channel_list = []
    summary = {
        'total_channels': len(channels_db),
        'total_subs_today': 0, 'total_views_today': 0, 'total_videos_today': 0,
        'total_subs_yesterday': 0, 'total_views_yesterday': 0
    }
    for ch in channels_db:
        stats = ChannelStats.query.filter_by(channel_id=ch.id).order_by(desc(ChannelStats.date)).limit(2).all()
        stats_today, stats_yesterday = (stats[0] if len(stats) > 0 else None), (stats[1] if len(stats) > 1 else None)
        if stats_today:
            summary['total_subs_today'] += stats_today.subscriber_count
            summary['total_views_today'] += stats_today.view_count
            summary['total_videos_today'] += stats_today.video_count
        if stats_yesterday:
            summary['total_subs_yesterday'] += stats_yesterday.subscriber_count
            summary['total_views_yesterday'] += stats_yesterday.view_count
        channel_list.append({
            "id": ch.id, "name": ch.name, "image_url": ch.image_url,
            "youtube_channel_id": ch.youtube_channel_id,
            "subscribers": stats_today.subscriber_count if stats_today else 0,
            "views": stats_today.view_count if stats_today else 0,
            "videos": stats_today.video_count if stats_today else 0,
            "daily_sub_change": (stats_today.subscriber_count - stats_yesterday.subscriber_count) if stats_today and stats_yesterday else 0,
            "daily_view_change": (stats_today.view_count - stats_yesterday.view_count) if stats_today and stats_yesterday else 0,
        })
    summary['daily_subs_change'] = summary['total_subs_today'] - summary['total_subs_yesterday']
    summary['daily_views_change'] = summary['total_views_today'] - summary['total_views_yesterday']
    summary['percent_subs_change'] = (summary['daily_subs_change'] / summary['total_subs_yesterday'] * 100) if summary['total_subs_yesterday'] else 0
    summary['percent_views_change'] = (summary['daily_views_change'] / summary['total_views_yesterday'] * 100) if summary['total_views_yesterday'] else 0
    return summary, sorted(channel_list, key=lambda x: x.get('subscribers', 0), reverse=True)

@app.route('/api/dashboard_data')
def get_dashboard_data():
    try:
        summary_data, channels_data = get_summary_and_channels_data()
        thirty_days_ago = date.today() - timedelta(days=30)
        historical_summary = db.session.query(
            ChannelStats.date,
            func.sum(ChannelStats.subscriber_count).label('total_subs'),
            func.sum(ChannelStats.view_count).label('total_views')
        ).filter(ChannelStats.date >= thirty_days_ago).group_by(ChannelStats.date).order_by(ChannelStats.date).all()
        return jsonify({
            "summary": summary_data, "channels": channels_data,
            "summary_chart": {
                'labels': [row.date.strftime('%b %d') for row in historical_summary],
                'subscribers': [row.total_subs for row in historical_summary],
                'views': [row.total_views for row in historical_summary]
            }
        })
    except Exception as e:
        print(f"Error in /api/dashboard_data: {e}")
        return jsonify({"error": "An internal error occurred", "details": str(e)}), 500

@app.route('/api/channels', methods=['POST'])
def add_channel():
    data = request.get_json()
    if not data or not data.get('channel_query'): abort(400, description="`channel_query` is required.")
    channel_id_to_add, error = find_channel_id_from_query(data['channel_query'])
    if error: abort(404, description=error)
    if Channel.query.filter_by(youtube_channel_id=channel_id_to_add).first():
        abort(409, description="This channel is already being tracked.")
    channel_data, error = fetch_channel_data_from_api(channel_id_to_add)
    if error: abort(500, description=error)
    new_channel = Channel(
        youtube_channel_id=channel_id_to_add, name=channel_data['name'],
        image_url=channel_data['image_url'],
        uploads_playlist_id=channel_data['uploads_playlist_id']
    )
    db.session.add(new_channel)
    db.session.flush()
    initial_stats = ChannelStats(
        channel_id=new_channel.id, subscriber_count=channel_data['subscriber_count'],
        view_count=channel_data['view_count'], video_count=channel_data['video_count']
    )
    db.session.add(initial_stats)
    db.session.commit()
    return jsonify({"message": "Channel added"}), 201

@app.route('/api/channels/<int:id>', methods=['DELETE'])
def delete_channel(id):
    channel = Channel.query.get_or_404(id)
    db.session.delete(channel)
    db.session.commit()
    return '', 204

@app.route('/api/channel_detail/<int:id>')
def get_channel_detail_data(id):
    try:
        channel = Channel.query.get_or_404(id)
        period = request.args.get('period', '30d')
        days_map = {'7d': 7, '30d': 30, '90d': 90, '1y': 365}
        days = days_map.get(period)
        query = ChannelStats.query.filter_by(channel_id=id)
        if period != 'all' and days:
             query = query.filter(ChannelStats.date >= (date.today() - timedelta(days=days)))
        all_stats_in_period = query.order_by(ChannelStats.date.asc()).all()
        stats_today, stats_period_start = (all_stats_in_period[-1] if all_stats_in_period else None), (all_stats_in_period[0] if all_stats_in_period else None)
        kpi_data = {
            'subs_total': stats_today.subscriber_count if stats_today else 0,
            'views_total': stats_today.view_count if stats_today else 0,
            'subs_change': (stats_today.subscriber_count - stats_period_start.subscriber_count) if stats_today and stats_period_start else 0,
            'views_change': (stats_today.view_count - stats_period_start.view_count) if stats_today and stats_period_start else 0,
        }
        recent_videos_data = []
        if channel.uploads_playlist_id:
            api_key = get_api_key()
            params_playlist = {'part': 'snippet', 'playlistId': channel.uploads_playlist_id, 'maxResults': 5, 'key': api_key}
            playlist_items = requests.get(f"{YOUTUBE_API_URL}playlistItems", params=params_playlist).json().get('items', [])
            if playlist_items:
                video_ids = [item['snippet']['resourceId']['videoId'] for item in playlist_items]
                params_videos = {'part': 'snippet,statistics', 'id': ','.join(video_ids), 'key': api_key}
                video_details = requests.get(f"{YOUTUBE_API_URL}videos", params=params_videos).json().get('items', [])
                for video in video_details:
                    stats = video.get('statistics', {})
                    recent_videos_data.append({
                        "id": video['id'], "title": video['snippet']['title'], "thumbnail": video['snippet']['thumbnails']['medium']['url'],
                        "view_count": int(stats.get('viewCount', 0)), "like_count": int(stats.get('likeCount', 0)),
                    })
        return jsonify({
            "kpi": kpi_data,
            "chart_data": {
                'labels': [s.date.strftime('%b %d, %Y') for s in all_stats_in_period],
                'subscribers': [s.subscriber_count for s in all_stats_in_period],
                'views': [s.view_count for s in all_stats_in_period],
            },
            "recent_videos": recent_videos_data
        })
    except Exception as e:
        print(f"Error in /api/channel_detail/{id}: {e}")
        return jsonify({"error": "An internal error occurred"}), 500

@app.route('/api/channels/<int:id>/export/csv')
def export_channel_csv(id):
    channel = Channel.query.get_or_404(id)
    period = request.args.get('period', 'all')
    query = ChannelStats.query.filter_by(channel_id=id)
    if period != 'all':
        days_map = {'7d': 7, '30d': 30, '90d': 90, '1y': 365}
        days = days_map.get(period)
        if days: query = query.filter(ChannelStats.date >= (date.today() - timedelta(days=days)))
    stats = query.order_by(ChannelStats.date.asc()).all()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Date', 'Subscribers', 'Total Views', 'Total Videos'])
    for stat in stats:
        cw.writerow([stat.date.isoformat(), stat.subscriber_count, stat.view_count, stat.video_count])
    output = si.getvalue()
    return Response(
        output, mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={channel.name.replace(' ', '_')}_export_{date.today()}.csv"}
    )

# --- 7. Uygulamayı Başlatma ---
if __name__ == '__main__':
    app.run(debug=True)