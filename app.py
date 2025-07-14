# app.py

import os
import requests
import subprocess
from datetime import date, datetime, timedelta
from flask import Flask, jsonify, render_template, request, abort, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, func

# --- GİT SENKRONİZASYON FONKSİYONLARI ---
def run_git_command(command):
    """Belirtilen git komutunu çalıştırır ve çıktısını yönetir."""
    try:
        print(f"Running command: {command}")
        # 'shell=True' ve 'check=True' önemli
        result = subprocess.run(command, capture_output=True, text=True, check=True, shell=True)
        if result.stdout:
            print(f"GIT STDOUT: {result.stdout.strip()}")
        if result.stderr:
            print(f"GIT STDERR: {result.stderr.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"GIT COMMAND FAILED: {command}\n{e.stderr.strip()}")
        return False

def sync_with_remote(pull_first=True, push_changes=False, commit_message="Sync changes from local app"):
    """GitHub ile senkronizasyonu yönetir."""
    if pull_first:
        print("\n--- Pulling latest changes from remote... ---")
        run_git_command("git pull")

    if push_changes:
        print("\n--- Pushing local changes to remote... ---")
        # Sadece instance/app.db dosyasında değişiklik var mı diye kontrol et
        status_result = subprocess.run("git status --porcelain instance/app.db", capture_output=True, text=True, shell=True)
        if not status_result.stdout:
            print("No local changes in database to push.")
            return

        run_git_command("git config --global user.name 'Analytica App'")
        run_git_command("git config --global user.email 'app@analytica.local'")
        run_git_command("git add instance/app.db")
        
        if run_git_command(f'git commit -m "{commit_message}"'):
            run_git_command("git push")

# --- Uygulama Başlarken Senkronizasyon ---
sync_with_remote(pull_first=True)


# --- 1. Flask ve SQLAlchemy Yapılandırması ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-super-secret-key-that-you-should-definitely-change'
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
os.makedirs(instance_path, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_path, 'app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/"


# --- 2. Veritabanı Modelleri ---
class Settings(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True, default=1)
    youtube_api_key = db.Column(db.String(100), nullable=True)

class Channel(db.Model):
    __tablename__ = 'channels'
    id = db.Column(db.Integer, primary_key=True)
    youtube_channel_id = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    nickname = db.Column(db.String(100), nullable=True)
    category = db.Column(db.String(50), nullable=True, default='Default')
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


# --- 3. Başlangıç ve Yardımcı Fonksiyonlar ---
def initial_setup():
    db.create_all()
    if Settings.query.first() is None:
        db.session.add(Settings(youtube_api_key=None))
        db.session.commit()

with app.app_context():
    initial_setup()

def get_api_key():
    settings = Settings.query.first()
    return settings.youtube_api_key if settings else None

def find_channel_id_from_query(query):
    api_key = get_api_key()
    if not api_key: return None, "API Key not set."
    if query.startswith(('UC', 'HC')) and len(query) == 24:
        params = {'part': 'id', 'id': query, 'key': api_key}
        response = requests.get(f"{YOUTUBE_API_URL}channels", params=params)
        if response.ok and response.json().get('items'): return query, None
    params = {'part': 'snippet', 'q': query, 'type': 'channel', 'maxResults': 1, 'key': api_key}
    response = requests.get(f"{YOUTUBE_API_URL}search", params=params)
    if not response.ok: return None, f"API search failed with status {response.status_code}."
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
    snippet, stats = item['snippet'], item.get('statistics', {})
    content_details = item.get('contentDetails', {})
    uploads_playlist_id = content_details.get('relatedPlaylists', {}).get('uploads')
    return {'name': snippet['title'], 'image_url': snippet['thumbnails']['default']['url'], 'uploads_playlist_id': uploads_playlist_id, 'subscriber_count': int(stats.get('subscriberCount', 0)), 'view_count': int(stats.get('viewCount', 0)), 'video_count': int(stats.get('videoCount', 0))}, None

def format_num_short(num):
    if num is None or not isinstance(num, (int, float)): return '0'
    num = float(num)
    if abs(num) >= 1_000_000: return f"{num/1_000_000:.2f}M"
    if abs(num) >= 1_000: return f"{num/1_000:.1f}K"
    return str(int(num))

def get_stats_at_date(channel_id, target_date):
    return ChannelStats.query.filter(ChannelStats.channel_id == channel_id, ChannelStats.date <= target_date).order_by(ChannelStats.date.desc()).first()

# --- 4. Rotalar ---
@app.route('/')
def index(): return render_template('index.html')
    
@app.route('/channel/<int:id>')
def channel_detail_page(id):
    channel = Channel.query.get_or_404(id)
    return render_template('channel_detail.html', channel=channel)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    app_settings = Settings.query.first()
    if not app_settings:
        app_settings = Settings(youtube_api_key=None)
        db.session.add(app_settings)
        db.session.commit()
    if request.method == 'POST':
        app_settings.youtube_api_key = request.form.get('api_key')
        db.session.commit()
        flash('API key saved successfully!', 'success')
        return redirect(url_for('settings'))
    return render_template('settings.html', current_key=app_settings.youtube_api_key or '')

# --- 5. API Rotaları ---
@app.route('/api/dashboard_data')
def get_dashboard_data():
    try:
        period = request.args.get('period', '30d')
        period_map = {'1d': 1, '7d': 7, '30d': 30, '90d': 90, '365d': 365, 'all': -1}
        period_days = period_map.get(period, 30)
        today = date.today()
        
        start_date_of_period = today - timedelta(days=period_days) if period != 'all' else date.min
        historical_summary_query = db.session.query(ChannelStats.date, func.sum(ChannelStats.subscriber_count).label('total_subs'), func.sum(ChannelStats.view_count).label('total_views'), func.sum(ChannelStats.video_count).label('total_videos'))
        if period != 'all':
            historical_summary_query = historical_summary_query.filter(ChannelStats.date >= start_date_of_period)
        historical_summary = historical_summary_query.group_by(ChannelStats.date).order_by(ChannelStats.date.asc()).all()

        if not historical_summary: return jsonify({ "summary": [], "chart_data": {"labels": [], "subscribers": [], "views": []}, "channels": [], "top_performers": [] })

        all_channels = Channel.query.all()
        channels_list = []
        for channel in all_channels:
            channel_data = {'id': channel.id, 'name': channel.name, 'nickname': channel.nickname, 'category': channel.category, 'image_url': channel.image_url, 'youtube_channel_id': channel.youtube_channel_id}
            latest_stat = get_stats_at_date(channel.id, today)
            if not latest_stat: continue
            channel_data.update({'subscribers': latest_stat.subscriber_count, 'views': latest_stat.view_count, 'videos': latest_stat.video_count})
            for p_key, p_days in {'1d': 1, '7d': 7, '30d': 30, '365d': 365}.items():
                p_start_stat = get_stats_at_date(channel.id, today - timedelta(days=p_days))
                if p_start_stat:
                    channel_data[f'subs_change_{p_key}'], channel_data[f'views_change_{p_key}'], channel_data[f'videos_change_{p_key}'] = latest_stat.subscriber_count - p_start_stat.subscriber_count, latest_stat.view_count - p_start_stat.view_count, latest_stat.video_count - p_start_stat.video_count
                else:
                    channel_data[f'subs_change_{p_key}'], channel_data[f'views_change_{p_key}'], channel_data[f'videos_change_{p_key}'] = 0, 0, 0
            channels_list.append(channel_data)
        
        latest_total_stats, start_total_stats = historical_summary[-1], historical_summary[0]
        subs_change, views_change, videos_change = latest_total_stats.total_subs - start_total_stats.total_subs, latest_total_stats.total_views - start_total_stats.total_views, latest_total_stats.total_videos - start_total_stats.total_videos
        summary_data = [
            {"id": "subs", "title": "Subscribers", "value": format_num_short(latest_total_stats.total_subs), "change": f"{'+' if subs_change >= 0 else ''}{format_num_short(subs_change)}", "isPositive": subs_change >= 0},
            {"id": "views", "title": "Views", "value": format_num_short(latest_total_stats.total_views), "change": f"{'+' if views_change >= 0 else ''}{format_num_short(views_change)}", "isPositive": views_change >= 0},
            {"id": "videos", "title": "Videos", "value": f"{latest_total_stats.total_videos:,}", "change": f"{'+' if videos_change >= 0 else ''}{videos_change}", "isPositive": videos_change >= 0},
            {"id": "channels", "title": "Tracked Channels", "value": len(all_channels), "change": "", "isPositive": True},
        ]
        return jsonify({"summary": summary_data, "chart_data": {'labels': [s.date.strftime('%b %d') for s in historical_summary], 'subscribers': [s.total_subs for s in historical_summary], 'views': [s.total_views for s in historical_summary]}, "channels": channels_list})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/api/channel_detail_data/<int:id>')
def get_channel_detail_api(id):
    try:
        channel = Channel.query.get_or_404(id)
        period = request.args.get('period', '30d')
        period_map = {'7d': 7, '30d': 30, '90d': 90, '365d': 365, 'all': -1}
        period_days = period_map.get(period, 30)
        start_date = date.today() - timedelta(days=period_days) if period != 'all' else date.min
        stats_query = ChannelStats.query.filter_by(channel_id=id)
        if period != 'all': stats_query = stats_query.filter(ChannelStats.date >= start_date)
        all_stats = stats_query.order_by(ChannelStats.date.asc()).all()
        if not all_stats: return jsonify({"kpi": {}, "chart_data": {"labels": [], "subscribers": [], "views": []}, "recent_videos": []})
        latest_stat, start_stat = all_stats[-1], all_stats[0]
        kpi_data = {'subs_total': latest_stat.subscriber_count, 'views_total': latest_stat.view_count, 'videos_total': latest_stat.video_count, 'subs_change': latest_stat.subscriber_count - start_stat.subscriber_count, 'views_change': latest_stat.view_count - start_stat.view_count}
        recent_videos, api_key = [], get_api_key()
        if channel.uploads_playlist_id and api_key:
            params_playlist = {'part': 'snippet', 'playlistId': channel.uploads_playlist_id, 'maxResults': 6, 'key': api_key}
            playlist_res = requests.get(f"{YOUTUBE_API_URL}playlistItems", params=params_playlist)
            if playlist_res.ok:
                video_ids = [item['snippet']['resourceId']['videoId'] for item in playlist_res.json().get('items', [])]
                if video_ids:
                    params_videos = {'part': 'snippet,statistics', 'id': ','.join(video_ids), 'key': api_key}
                    videos_res = requests.get(f"{YOUTUBE_API_URL}videos", params=params_videos)
                    if videos_res.ok:
                        for video in videos_res.json().get('items', []):
                            stats = video.get('statistics', {})
                            recent_videos.append({"id": video['id'], "title": video['snippet']['title'], "thumbnail": video['snippet']['thumbnails']['medium']['url'], "view_count": int(stats.get('viewCount', 0)), "like_count": int(stats.get('likeCount', 0))})
        return jsonify({"kpi": kpi_data, "chart_data": {'labels': [s.date.strftime('%b %d') for s in all_stats], 'subscribers': [s.subscriber_count for s in all_stats], 'views': [s.view_count for s in all_stats]}, "recent_videos": recent_videos})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": "An internal server error occurred."}), 500

@app.route('/api/channel/<int:id>')
def get_channel_data(id):
    channel = Channel.query.get_or_404(id)
    return jsonify({'id': channel.id, 'name': channel.name, 'nickname': channel.nickname, 'category': channel.category})

@app.route('/api/channels', methods=['POST'])
def add_channel():
    data = request.get_json()
    if not data or not data.get('channel_query'): return jsonify({"error": "Channel query is required."}), 400
    channel_id, error = find_channel_id_from_query(data['channel_query'])
    if error: return jsonify({"error": error}), 404
    if Channel.query.filter_by(youtube_channel_id=channel_id).first(): return jsonify({"error": "This channel is already being tracked."}), 409
    channel_data, error = fetch_channel_data_from_api(channel_id)
    if error: return jsonify({"error": error}), 500
    new_channel = Channel(youtube_channel_id=channel_id, name=channel_data['name'], image_url=channel_data['image_url'], uploads_playlist_id=channel_data['uploads_playlist_id'])
    db.session.add(new_channel)
    db.session.flush()
    db.session.add(ChannelStats(channel_id=new_channel.id, subscriber_count=channel_data['subscriber_count'], view_count=channel_data['view_count'], video_count=channel_data['video_count']))
    db.session.commit()
    sync_with_remote(pull_first=False, push_changes=True, commit_message=f"Add channel: {channel_data['name']}")
    return jsonify({"message": f"Channel '{channel_data['name']}' added successfully."}), 201

@app.route('/api/channels/<int:id>/update', methods=['POST'])
def update_channel(id):
    channel = Channel.query.get_or_404(id)
    data = request.get_json()
    channel.nickname = data.get('nickname')
    channel.category = data.get('category')
    db.session.commit()
    sync_with_remote(pull_first=False, push_changes=True, commit_message=f"Update channel: {channel.name}")
    return jsonify({"message": "Channel updated."})

@app.route('/api/channels/<int:id>', methods=['DELETE'])
def delete_channel(id):
    channel = Channel.query.get_or_404(id)
    channel_name = channel.name
    db.session.delete(channel)
    db.session.commit()
    sync_with_remote(pull_first=False, push_changes=True, commit_message=f"Delete channel: {channel_name}")
    return '', 204

if __name__ == '__main__':
    app.run(debug=True)