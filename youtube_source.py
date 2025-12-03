#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTubeCÕ;K‰Å1’Ö—Y‹â¸åüë
ºøÇÕ;n½ü¹hj‹CÕ;nÅ1’½ú
"""

import os
import re
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs

# YouTube Data APIª×·çó	
try:
    from googleapiclient.discovery import build
    YOUTUBE_API_AVAILABLE = True
except ImportError:
    YOUTUBE_API_AVAILABLE = False

# youtube-transcript-apiWUÖ—(	
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    TRANSCRIPT_API_AVAILABLE = True
except ImportError:
    TRANSCRIPT_API_AVAILABLE = False


def extract_video_id(url: str) -> Optional[str]:
    """YouTubenURLK‰Õ;ID’½ú"""
    if not url:
        return None

    # ØjYouTube URLÑ¿üókşÜ
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def get_video_transcript(video_id: str, language: str = 'ja') -> Optional[str]:
    """Õ;nWU’Ö—"""
    if not TRANSCRIPT_API_AVAILABLE:
        print("  youtube-transcript-api L¤ó¹ÈüëUŒfD~[“")
        print("   pip install youtube-transcript-api g¤ó¹ÈüëWfO`UD")
        return None

    try:
        # å,WU’*HjQŒpêÕWU
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        try:
            transcript = transcript_list.find_transcript([language])
        except:
            # êÕWU’fY
            try:
                transcript = transcript_list.find_generated_transcript([language])
            except:
                # ñg‚fY
                try:
                    transcript = transcript_list.find_transcript(['en'])
                except:
                    return None

        # Æ­¹È’P
        full_text = " ".join([entry['text'] for entry in transcript.fetch()])
        return full_text

    except Exception as e:
        print(f"  WUÖ—¨éü: {e}")
        return None


def get_video_info_from_api(video_id: str, api_key: str) -> Optional[Dict]:
    """YouTube Data APIK‰Õ;Å1’Ö—"""
    if not YOUTUBE_API_AVAILABLE:
        return None

    try:
        youtube = build('youtube', 'v3', developerKey=api_key)

        request = youtube.videos().list(
            part='snippet,contentDetails,statistics',
            id=video_id
        )
        response = request.execute()

        if not response.get('items'):
            return None

        item = response['items'][0]
        snippet = item['snippet']

        return {
            'title': snippet.get('title', ''),
            'description': snippet.get('description', ''),
            'channel_title': snippet.get('channelTitle', ''),
            'published_at': snippet.get('publishedAt', ''),
            'view_count': item.get('statistics', {}).get('viewCount', 0),
            'tags': snippet.get('tags', [])
        }

    except Exception as e:
        print(f"  YouTube API ¨éü: {e}")
        return None


def summarize_with_gemini(text: str, model) -> str:
    """GeminigøÇ…¹’û½ú"""
    prompt = f"""
ånYouTubeÕ;nWUÆ­¹ÈK‰ºøÇn…¹’½úWfO`UD

WUÆ­¹È
{text[:10000]}  # wYN‹4oŠp

ú›b
ånbgú›WfO`UD

øÇ: tbû'%ûwmjiK‹Å1	
øÇ…¹:
øÇns0’300500‡W¦g	

n’ú›WfO`UD
"""

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"  Gemini¨éü: {e}")
        return text[:1000]


def get_source_video_info(video_url: str, gemini_model=None, youtube_api_key: str = None) -> Dict:
    """
    CÕ;nÅ1’Ö—Y‹á¤ó¢p

    Args:
        video_url: YouTubeÕ;nURL
        gemini_model: GeminiâÇë(ª×·çó	
        youtube_api_key: YouTube Data API ­üª×·çó	

    Returns:
        dict: Õ;Å1
            - title: Õ;¿¤Èë
            - summary: øÇ…¹n
            - consultation: øÇ…¹ns0
            - url: CÕ;URL
            - transcript: WUÆ­¹ÈÖ—gM_4	
    """
    result = {
        'title': '',
        'summary': '',
        'consultation': '',
        'url': video_url,
        'transcript': None
    }

    # Õ;ID’½ú
    video_id = extract_video_id(video_url)
    if not video_id:
        print(f"  Õ;ID’½úgM~[“: {video_url}")
        return result

    print(f"=ù Õ;ID: {video_id}")

    # YouTube APIK‰ú,Å1’Ö—
    if youtube_api_key:
        api_info = get_video_info_from_api(video_id, youtube_api_key)
        if api_info:
            result['title'] = api_info.get('title', '')
            result['summary'] = api_info.get('description', '')[:500]
            print(f" APIÅ1Ö—Ÿ: {result['title'][:50]}...")

    # WU’Ö—
    transcript = get_video_transcript(video_id)
    if transcript:
        result['transcript'] = transcript
        print(f" WUÖ—Ÿ: {len(transcript)}‡W")

        # Geminig
        if gemini_model:
            summary = summarize_with_gemini(transcript, gemini_model)
            result['consultation'] = summary
            if not result['summary']:
                result['summary'] = summary[:200]
            print(" øÇ…¹’½úW~W_")

    return result


# Æ¹È(
if __name__ == "__main__":
    # Æ¹ÈŸL
    test_url = "https://www.youtube.com/watch?v=XXXXXXXXXXX"

    print("=" * 50)
    print("YouTube Source Æ¹È")
    print("=" * 50)

    video_id = extract_video_id(test_url)
    print(f"Õ;ID: {video_id}")

    if video_id:
        transcript = get_video_transcript(video_id)
        if transcript:
            print(f"WU: {transcript[:200]}...")
        else:
            print("WU’Ö—gM~[“gW_")
