#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import base64
import tempfile
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import re
import io

# Google関連のインポート
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import gspread
from google.auth.transport.requests import Request

# その他
from PIL import Image, ImageDraw, ImageFont
import requests
from gtts import gTTS
from pydub import AudioSegment
import numpy as np

# ============================================================
# 定数設定
# ============================================================
SCRIPT_NAME = "朝ドラ「ばけばけ」動画生成システム"
VERSION = "2.0.0"
OUTPUT_DIR = Path("output")
TEMP_DIR = Path("temp")
ASSETS_DIR = Path("assets")

# 動画設定
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30
VIDEO_DURATION = 60  # 秒

# フォント設定
FONT_SIZE_TITLE = 72
FONT_SIZE_SUBTITLE = 48
FONT_SIZE_DIALOG = 36
FONT_COLOR_MAIN = "#FFFFFF"
FONT_COLOR_SHADOW = "#000000"

# YouTube設定
YOUTUBE_TITLE_TEMPLATE = "【朝ドラ考察】ばけばけ 第{episode}話 みんなの反応まとめ"
YOUTUBE_DESCRIPTION_TEMPLATE = """
朝ドラ「ばけばけ」第{episode}話のネット上の反応をまとめました！

アイドルグループ風の
