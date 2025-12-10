from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import yt_dlp
import requests
import uuid
import sys
import os

app = Flask(__name__)

# In-memory session cache
VIDEO_CACHE = {}

# Configure yt-dlp options
YDL_OPTIONS = {
    'format': 'best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'cache_dir': '/tmp/yt-dlp-cache', # Use writable directory for cache
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_video_info():
    data = request.get_json()
    url = data.get('url')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        opts = YDL_OPTIONS.copy()
        opts['noplaylist'] = False 

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            entries = []
            if 'entries' in info:
                entries = list(info['entries'])
            else:
                entries = [info]

            processed_videos = []

            for entry in entries:
                vid_id = str(uuid.uuid4())
                
                req_headers = entry.get('http_headers', {})
                cookies_str = entry.get('cookies')
                cookies_dict = {}
                if cookies_str and isinstance(cookies_str, str):
                    for cookie in cookies_str.split('; '):
                        if '=' in cookie:
                            k, v = cookie.split('=', 1)
                            cookies_dict[k] = v

                VIDEO_CACHE[vid_id] = {
                    'url': entry.get('url'),
                    'headers': req_headers,
                    'cookies': cookies_dict,
                    'title': entry.get('title', 'video')
                }

                video_data = {
                    'id': vid_id,
                    'title': entry.get('title', 'Unknown Title'),
                    'thumbnail': entry.get('thumbnail', ''),
                    'duration': entry.get('duration', 0),
                    'uploader': entry.get('uploader', 'Unknown'),
                    'stream_url': f'/stream/{vid_id}',
                    'original_url': entry.get('url', ''),
                    'formats': []
                }
                
                fmts = entry.get('formats', [])
                if not fmts:
                     video_data['formats'].append({
                        'resolution': 'Default',
                        'ext': entry.get('ext', 'mp4'),
                        'filesize': entry.get('filesize', 0),
                        'url': f'/stream/{vid_id}?dl=1'
                    })
                else:
                    for f in fmts:
                         video_data['formats'].append({
                            'format_id': f.get('format_id', '0'),
                            'ext': f.get('ext', 'mp4'),
                            'resolution': f.get('resolution', 'Unknown'),
                            'filesize': f.get('filesize', 0),
                            'url': f['url']
                        })
                    
                    video_data['formats'].insert(0, {
                        'format_id': 'proxy',
                        'ext': entry.get('ext', 'mp4'),
                        'resolution': 'Best (Proxy)',
                        'filesize': entry.get('filesize', 0),
                        'url': f'/stream/{vid_id}?dl=1'
                    })

                processed_videos.append(video_data)
            
            if not processed_videos:
                 return jsonify({'error': 'No video found'}), 404

            return jsonify(processed_videos[0]) 

    except Exception as e:
        app.logger.error(f"Error extracting info: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stream/<vid_id>')
def stream_video(vid_id):
    video_info = VIDEO_CACHE.get(vid_id)
    if not video_info:
        return "Video link expired or invalid", 404

    url = video_info['url']
    headers = video_info['headers']
    cookies = video_info['cookies']
    
    is_download = request.args.get('dl') == '1'

    try:
        req = requests.get(url, headers=headers, cookies=cookies, stream=True)
        
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        resp_headers = [(name, value) for (name, value) in req.headers.items()
                        if name.lower() not in excluded_headers]
        
        if is_download:
            resp_headers.append(('Content-Disposition', f'attachment; filename="{video_info["title"]}.{video_info.get("ext", "mp4")}"'))

        return Response(stream_with_context(req.iter_content(chunk_size=1024*8)),
                        headers=resp_headers,
                        status=req.status_code,
                        content_type=req.headers.get('content-type'))
    except Exception as e:
        return f"Error proxying stream: {e}", 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
