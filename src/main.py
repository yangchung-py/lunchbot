import os
import requests
import argparse
import schedule
import time
import re
import logging
from datetime import datetime, timedelta
from instagrapi import Client
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from collections import Counter
from bs4 import BeautifulSoup
import urllib3
import httpx
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================
# 환경 변수 및 상수 설정
# =========================
load_dotenv()

IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
NX = os.getenv("NX")  # 학교 좌표 X
NY = os.getenv("NY")  # 학교 좌표 Y

IG_CREDENTIAL_PATH = "./ig_settings.json"
IG_IMAGE_PATH = "./menu"
FONT_PATH = "font.ttf"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT}

# =========================
# 로깅 설정
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# =========================
# 인스타그램 봇 클래스
# =========================
class InstagramBot:
    """인스타그램 스토리 업로드용 봇"""
    def __init__(self):
        self._cl = Client()
        if os.path.exists(IG_CREDENTIAL_PATH):
            self._cl.load_settings(IG_CREDENTIAL_PATH)
        self._cl.login(IG_USERNAME, IG_PASSWORD)
        self._cl.dump_settings(IG_CREDENTIAL_PATH)

    def upload_story(self, image_path: str):
        logger.info(f"Uploading story: {image_path}")
        self._cl.photo_upload_to_story(image_path)
        logger.info("Story uploaded successfully.")

# =========================
# 날씨 데이터 관련 함수
# =========================
def get_weather_data():
    """기상청 초단기예보 API에서 오늘의 날씨 데이터 가져오기"""
    now = datetime.now()
    try:
        # API 요청 시간 계산
        adjusted_time = now - timedelta(minutes=40)
        base_hour = adjusted_time.hour
        base_minute = 30 if adjusted_time.minute >= 30 else 0
        base_time_dt = adjusted_time.replace(minute=base_minute, second=0, microsecond=0)
        if adjusted_time.minute < 30:
            base_time_dt = base_time_dt - timedelta(hours=1)
        base_date = base_time_dt.strftime("%Y%m%d")
        base_time = base_time_dt.strftime("%H%M")

        url = (
            f'http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst?'
            f'serviceKey={WEATHER_API_KEY}&pageNo=1&numOfRows=1000&dataType=JSON'
            f'&base_date={base_date}&base_time=0630&nx={NX}&ny={NY}'
        )
        logger.debug(f"요청 URL: {url}")

        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        # 응답 구조 확인
        items = (
            data.get('response', {})
                .get('body', {})
                .get('items', {})
                .get('item', [])
        )
        if not items:
            logger.error(f"API 응답에 item이 없습니다: {data}")
            return None

        today = now.strftime("%Y%m%d")
        forecasts = {}
        for item in items:
            if item['fcstDate'] != today:
                continue
            fcst_time = item['fcstTime']
            category = item['category']
            value = item['fcstValue']
            forecasts.setdefault(fcst_time, {})[category] = value

        # 데이터 분석
        temps, humidities, sky_codes, precip_types_list, precip_times = [], [], [], [], []
        precip_sum = 0.0
        for time_str in sorted(forecasts.keys()):
            data = forecasts[time_str]
            # 온도
            if 'T1H' in data:
                try: temps.append(float(data['T1H']))
                except: pass
            # 습도
            if 'REH' in data:
                try: humidities.append(float(data['REH']))
                except: pass
            # 하늘 상태
            if 'SKY' in data:
                sky_codes.append(data['SKY'])
            # 강수 형태
            pty = data.get('PTY', '0')
            if pty != '0':
                precip_type_map = {
                    '0': '없음', '1': '비', '2': '비/눈', '3': '눈', '4': '소나기',
                    '5': '빗방울', '6': '빗방울눈날림', '7': '눈날림'
                }
                precip_types_list.append(precip_type_map.get(pty, f'알 수 없음({pty})'))
            # 강수량
            rn1 = data.get('RN1', '0')
            if rn1 not in ['0', '강수없음']:
                try:
                    if rn1 == '1mm 미만':
                        precip_sum += 0.5
                    elif 'mm' in rn1:
                        precip_sum += float(re.search(r'(\d+\.?\d*)', rn1).group(1))
                    else:
                        precip_sum += float(rn1)
                except: pass
            # 강수 시간대
            if pty != '0' or rn1 not in ['0', '강수없음']:
                precip_times.append(f"{time_str[:2]}:{time_str[2:]}")

        # 강수 시간대 그룹화
        time_ranges = group_time_ranges(precip_times)
        # 하늘 상태 결정
        sky_condition = get_most_common_sky(sky_codes)
        # 강수 형태 결정
        precip_type = get_most_common_precip(precip_types_list)
        # 최종 날씨 상태
        weather_status = f"{sky_condition}{precip_type}"

        return {
            'date': now.strftime("%m월 %d일"),
            'avg_temp': sum(temps)/len(temps) if temps else None,
            'avg_humidity': sum(humidities)/len(humidities) if humidities else None,
            'weather_status': weather_status,
            'precip_times': time_ranges,
            'precip_sum': precip_sum
        }
    except Exception as e:
        logger.error(f"Weather error: {e}", exc_info=True)
        return None

def group_time_ranges(times):
    """시간 리스트를 연속 구간으로 그룹화"""
    if not times:
        return []
    sorted_times = sorted(times)
    time_ranges = []
    current_start = current_end = sorted_times[0]
    for t in sorted_times[1:]:
        if int(t.replace(':', '')) - int(current_end.replace(':', '')) == 100:
            current_end = t
        else:
            time_ranges.append(f"{current_start}~{current_end}" if current_start != current_end else current_start)
            current_start = current_end = t
    time_ranges.append(f"{current_start}~{current_end}" if current_start != current_end else current_start)
    return time_ranges

def get_most_common_sky(sky_codes):
    """가장 많이 나온 하늘 상태 반환"""
    if not sky_codes:
        return "정보 없음"
    sky_map = {'1': '맑음', '3': '구름많음', '4': '흐림'}
    most_common = Counter(sky_codes).most_common(1)[0][0]
    return sky_map.get(most_common, '알 수 없음')

def get_most_common_precip(precip_types):
    """가장 많이 나온 강수 형태 반환"""
    if not precip_types:
        return ""
    most_common = Counter(precip_types).most_common(1)[0][0]
    return f", {most_common}"

# =========================
# 이미지 생성 함수
# =========================
def create_weather_image(weather, output_path=None):
    """날씨 정보를 이미지로 생성"""
    img = Image.new('RGB', (1080, 1920), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    title_font, label_font, value_font, source_font = load_fonts()

    # 제목
    title = f"{weather['date']} 날씨"
    draw_centered_text(draw, title, 350, title_font)
    # 출처
    draw_centered_text(draw, "출처: 기상청 초단기예보", 430, source_font, color=(100,100,100))

    # 날씨 정보 항목
    items = [
        ("하늘 상태", weather['weather_status']),
        ("평균 온도", f"{weather['avg_temp']:.1f}℃" if weather['avg_temp'] else "정보없음"),
        ("평균 습도", f"{weather['avg_humidity']:.1f}%" if weather['avg_humidity'] else "정보없음"),
        ("강수 시간대", ", ".join(weather['precip_times']) if weather['precip_times'] else "X"),
        ("강수량", f"{weather['precip_sum']:.1f}mm" if weather['precip_sum'] > 0 else "X")
    ]
    current_y = 700
    for label, value in items:
        draw_label_value(draw, label, value, current_y, label_font, value_font)
        current_y += 100

    path = output_path or f"{IG_IMAGE_PATH}/{datetime.now().strftime('%Y%m%d')}_weather.jpg"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    logger.info(f"Weather image created: {path}")
    return path

def create_menu_image(menu_text, meal_type, suffix):
    """급식 메뉴 이미지를 생성"""
    if menu_text is None:
        return None
    image = Image.new('RGB', (1080, 1920), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = load_font(FONT_PATH, 60)
    full_text = f"{meal_type}\n\n{menu_text}"
    text_bbox = draw.textbbox((0, 0), full_text, font=font)
    x = (1080 - (text_bbox[2] - text_bbox[0])) / 2
    y = (1920 - (text_bbox[3] - text_bbox[1])) / 2
    draw.text((x, y), full_text, fill=(0,0,0), font=font)
    today = datetime.now().strftime('%Y%m%d')
    image_path = f'{IG_IMAGE_PATH}/{today}{suffix}.jpg'
    os.makedirs(os.path.dirname(image_path), exist_ok=True)
    image.save(image_path)
    logger.info(f"Menu image created: {image_path}")
    return image_path

def load_fonts():
    """여러 크기의 폰트 로드"""
    try:
        return (
            ImageFont.truetype(FONT_PATH, 60),
            ImageFont.truetype(FONT_PATH, 50),
            ImageFont.truetype(FONT_PATH, 48),
            ImageFont.truetype(FONT_PATH, 38),
        )
    except:
        return (
            ImageFont.load_default(),
            ImageFont.load_default(),
            ImageFont.load_default(),
            ImageFont.load_default(),
        )

def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except:
        return ImageFont.load_default()

def draw_centered_text(draw, text, y, font, color=(0,0,0)):
    bbox = draw.textbbox((0,0), text, font=font)
    width = bbox[2] - bbox[0]
    draw.text(((1080-width)/2, y), text, color, font=font)

def draw_label_value(draw, label, value, y, label_font, value_font):
    text = f"{label}: {value}"
    bbox = draw.textbbox((0,0), text, font=label_font)
    width = bbox[2] - bbox[0]
    if width > 900:
        # 두 줄로 나누기
        label_bbox = draw.textbbox((0,0), label+":", font=label_font)
        label_width = label_bbox[2] - label_bbox[0]
        draw.text(((1080-label_width)/2, y), label+":", (0,0,0), font=label_font)
        y += 70
        value_bbox = draw.textbbox((0,0), value, font=value_font)
        value_width = value_bbox[2] - value_bbox[0]
        draw.text(((1080-value_width)/2, y), value, (0,0,0), font=value_font)
    else:
        draw.text(((1080-width)/2, y), text, (0,0,0), font=label_font)

# =========================
# 급식 메뉴 관련 함수
# =========================
def get_meal_menu(meal_code):
    """오늘의 급식 메뉴를 가져옴 (2: 중식, 3: 석식)"""
    today = datetime.now().strftime('%Y%m%d')
    url = (
        f'https://open.neis.go.kr/hub/mealServiceDietInfo?Type=json&pSize=100'
        f'&ATPT_OFCDC_SC_CODE=B10&SD_SCHUL_CODE=7010208&MMEAL_SC_CODE={meal_code}&MLSV_YMD={today}'
    )
    try:
        logger.info(f"Fetching {'lunch' if meal_code == 2 else 'dinner'} menu...")
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if 'mealServiceDietInfo' in data:
            menu_items = data['mealServiceDietInfo'][1]['row'][0]['DDISH_NM'].split('<br/>')
            cleaned_menu = [re.sub(r'\s*\([^)]*\)', '', item.replace('y', '').strip()) for item in menu_items]
            menu = '\n'.join(cleaned_menu)
            logger.info(f"{'Lunch' if meal_code == 2 else 'Dinner'} menu fetched successfully.")
        else:
            menu = None
            logger.warning(f"{'Lunch' if meal_code == 2 else 'Dinner'} menu not found.")
    except Exception as e:
        menu = None
        logger.error(f"Error fetching meal menu: {e}")
    return menu

# =========================
# 급식 이미지 크롤링 및 다운로드 함수
# =========================
def fetch_lunch_image_url():
    """양정고 오늘의 급식 이미지 URL을 크롤링해서 반환 (httpx 사용)"""
    url = "https://yangchung.sen.hs.kr"
    try:
        with httpx.Client(headers=HEADERS, verify=False, timeout=10) as client:
            resp = client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            lunch_section = None
            for h3 in soup.find_all("h3"):
                if "오늘의 급식" in h3.text:
                    lunch_section = h3.find_parent("div")
                    break
            if not lunch_section:
                logger.warning("오늘의 급식 섹션을 찾지 못했습니다.")
                return None
            img_tag = lunch_section.find("img")
            if not img_tag or not img_tag.get("src"):
                logger.warning("오늘의 급식 이미지가 없습니다.")
                return None
            img_url = img_tag["src"]
            if img_url.startswith("/"):
                img_url = url + img_url
            return img_url
    except Exception as e:
        logger.error(f"급식 이미지 크롤링 실패: {e}")
        return None

def download_image(url, save_path):
    try:
        with httpx.Client(headers=HEADERS, verify=False, timeout=10) as client:
            resp = client.get(url)
            resp.raise_for_status()
            with open(save_path, "wb") as f:
                f.write(resp.content)
        logger.info(f"이미지 다운로드 완료: {save_path}")
        return save_path
    except Exception as e:
        logger.error(f"이미지 다운로드 실패: {e}")
        return None

# =========================
# 급식 이미지 템플릿 합성 함수
# =========================
def create_menu_story_image_with_photo(menu_text, meal_type, photo_path, suffix):
    """급식 텍스트와 급식 이미지를 합성하여 스토리용 이미지 생성"""
    if menu_text is None or photo_path is None:
        return None
    # 배경
    image = Image.new('RGB', (1080, 1920), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = load_font(FONT_PATH, 60)
    # 텍스트
    full_text = f"{meal_type}\n\n{menu_text}"
    text_bbox = draw.textbbox((0, 0), full_text, font=font)
    text_x = (1080 - (text_bbox[2] - text_bbox[0])) / 2
    text_y = 200
    draw.text((text_x, text_y), full_text, fill=(0,0,0), font=font)
    # 급식 이미지 삽입 (비율 유지, 여백)
    try:
        meal_img = Image.open(photo_path).convert("RGB")
        # 최대 크기(여백 포함)
        max_w, max_h = 900, 900
        meal_img.thumbnail((max_w, max_h), Image.LANCZOS)
        # 중앙 배치 (텍스트 아래)
        img_x = (1080 - meal_img.width) // 2
        img_y = text_y + (text_bbox[3] - text_bbox[1]) + 80
        image.paste(meal_img, (img_x, img_y))
    except Exception as e:
        logger.error(f"급식 이미지 합성 실패: {e}")
    today = datetime.now().strftime('%Y%m%d')
    image_path = f'{IG_IMAGE_PATH}/{today}{suffix}_photo.jpg'
    os.makedirs(os.path.dirname(image_path), exist_ok=True)
    image.save(image_path)
    logger.info(f"Menu+Photo story image created: {image_path}")
    return image_path

# =========================
# 급식 이미지만 합성 함수 (텍스트 없이)
# =========================
def create_menu_photo_story_image(photo_path, suffix, menu_text=None):
    """이미지는 상단(중앙), 메뉴 텍스트(중식 제외)는 하단에 폰트 작게 배치"""
    if photo_path is None:
        return None
    image = Image.new('RGB', (1080, 1920), (255, 255, 255))
    # 1. 이미지 상단 중앙 배치
    try:
        meal_img = Image.open(photo_path).convert("RGB")
        max_w, max_h = 900, 900
        meal_img.thumbnail((max_w, max_h), Image.LANCZOS)
        img_x = (1080 - meal_img.width) // 2
        img_y = 120  # 상단 여백
        image.paste(meal_img, (img_x, img_y))
    except Exception as e:
        logger.error(f"급식 이미지 합성 실패: {e}")
    # 2. 메뉴 텍스트(중식 제외) 하단 배치
    if menu_text:
        # '중식'이라는 단어 제거 및 앞뒤 공백/개행 정리
        menu_text = menu_text.replace('중식', '').strip()
        # 폰트 작게
        font = load_font(FONT_PATH, 38)
        draw = ImageDraw.Draw(image)
        # 여러 줄로 나누기
        lines = menu_text.split('\n')
        # 하단 기준 y좌표
        total_height = len(lines) * 55
        start_y = 1920 - total_height - 80  # 하단에서 80px 위
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0,0), line, font=font)
            width = bbox[2] - bbox[0]
            x = (1080 - width) // 2
            y = start_y + i * 55
            draw.text((x, y), line, fill=(30,30,30), font=font)
    today = datetime.now().strftime('%Y%m%d')
    image_path = f'{IG_IMAGE_PATH}/{today}{suffix}_photo_only.jpg'
    os.makedirs(os.path.dirname(image_path), exist_ok=True)
    image.save(image_path)
    logger.info(f"Menu photo-only story image created: {image_path}")
    return image_path

# =========================
# SSL 에러 우회 크롤링
# =========================
def fetch_lunch_image_url_ssl_safe():
    url = "https://yangchung.sen.hs.kr"
    try:
        return fetch_lunch_image_url()
    except Exception as e:
        logger.warning(f"SSL/기타 에러 발생, 인증서 검증 없이 재시도: {e}")
        try:
            with httpx.Client(headers=HEADERS, verify=False, timeout=10) as client:
                resp = client.get(url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                lunch_section = None
                for h3 in soup.find_all("h3"):
                    if "오늘의 급식" in h3.text:
                        lunch_section = h3.find_parent("div")
                        break
                if not lunch_section:
                    logger.warning("오늘의 급식 섹션을 찾지 못했습니다.")
                    return None
                img_tag = lunch_section.find("img")
                if not img_tag or not img_tag.get("src"):
                    logger.warning("오늘의 급식 이미지가 없습니다.")
                    return None
                img_url = img_tag["src"]
                if img_url.startswith("/"):
                    img_url = url + img_url
                return img_url
        except Exception as e2:
            logger.error(f"SSL 우회 후에도 급식 이미지 크롤링 실패: {e2}")
            return None

# =========================
# 세분화된 업로드 함수
# =========================
def upload_menu_story():
    bot = InstagramBot()
    lunch_menu = get_meal_menu(2)
    if lunch_menu:
        lunch_image_path = create_menu_image(lunch_menu, "중식", "_lunch")
        upload_story(bot, lunch_image_path)
    dinner_menu = get_meal_menu(3)
    if dinner_menu:
        dinner_image_path = create_menu_image(dinner_menu, "석식", "_dinner")
        upload_story(bot, dinner_image_path)

def upload_menu_image_story():
    bot = InstagramBot()
    lunch_menu = get_meal_menu(2)
    img_url = fetch_lunch_image_url()
    if lunch_menu and img_url:
        today = datetime.now().strftime('%Y%m%d')
        photo_path = f'{IG_IMAGE_PATH}/{today}_lunch_photo.jpg'
        download_image(img_url, photo_path)
        story_img_path = create_menu_story_image_with_photo(lunch_menu, "중식", photo_path, "_lunch")
        upload_story(bot, story_img_path)

def upload_weather_story():
    bot = InstagramBot()
    weather_data = get_weather_data()
    if weather_data:
        weather_image = create_weather_image(weather_data)
        upload_story(bot, weather_image)

# =========================
# 07:00/11:50 스케줄 분리
# =========================
def job_text_menu_weather():
    bot = InstagramBot()
    # 중식 텍스트
    lunch_menu = get_meal_menu(2)
    if lunch_menu:
        lunch_image_path = create_menu_image(lunch_menu, "중식", "_lunch")
        upload_story(bot, lunch_image_path)
        time.sleep(10)
        # 날씨
        weather_data = get_weather_data()
        if weather_data:
            weather_image = create_weather_image(weather_data)
            upload_story(bot, weather_image)
    # 석식 텍스트
    dinner_menu = get_meal_menu(3)
    if dinner_menu:
        dinner_image_path = create_menu_image(dinner_menu, "석식", "_dinner")
        upload_story(bot, dinner_image_path)

def job_lunch_photo_only_story():
    lunch_menu = get_meal_menu(2)
    if lunch_menu:
        img_url = fetch_lunch_image_url_ssl_safe()
        if img_url:
            today = datetime.now().strftime('%Y%m%d')
            photo_path = f'{IG_IMAGE_PATH}/{today}_lunch_photo.jpg'
            download_image(img_url, photo_path)
            # 메뉴 텍스트에서 '중식' 제외하여 하단에 표시
            story_img_path = create_menu_photo_story_image(photo_path, "_lunch", menu_text=lunch_menu)
            bot = InstagramBot()
            upload_story(bot, story_img_path)

# =========================
# 스토리 업로드 및 전체 플로우
# =========================
def upload_story(bot, image_path):
    if image_path:
        bot.upload_story(image_path)

def fetch_and_upload_menu():
    bot = InstagramBot()
    # 중식
    lunch_menu = get_meal_menu(2)
    if lunch_menu:
        lunch_image_path = create_menu_image(lunch_menu, "중식", "_lunch")
        upload_story(bot, lunch_image_path)
        time.sleep(10)
        # 날씨 정보
        weather_data = get_weather_data()
        if weather_data:
            weather_image = create_weather_image(weather_data)
            upload_story(bot, weather_image)
    # 석식
    dinner_menu = get_meal_menu(3)
    if dinner_menu:
        dinner_image_path = create_menu_image(dinner_menu, "석식", "_dinner")
        upload_story(bot, dinner_image_path)

def generate_weather_image():
    weather_data = get_weather_data()
    if weather_data:
        return create_weather_image(weather_data, "./weather.png")
    return None

def job():
    fetch_and_upload_menu()

# =========================
# 스케줄 등록 및 메인 진입점
# =========================
def register_schedules():
    # 07:00 텍스트 중식/석식/날씨
    schedule.every().day.at("07:00").do(job_text_menu_weather)
    # 11:50 중식이 있는 날만 급식 이미지
    schedule.every().day.at("11:50").do(job_lunch_photo_only_story)

def main():
    parser = argparse.ArgumentParser(description="Upload Instagram story")
    parser.add_argument("--uploadnow", action="store_true", help="Upload the story immediately")
    parser.add_argument("--genweather", action="store_true", help="Generate weather image only")
    parser.add_argument("--uploadmenu", action="store_true", help="급식 텍스트 스토리 업로드")
    parser.add_argument("--uploadmenuimage", action="store_true", help="급식 이미지+텍스트 스토리 업로드")
    parser.add_argument("--uploadweather", action="store_true", help="날씨 스토리 업로드")
    args = parser.parse_args()

    if args.uploadmenu:
        upload_menu_story()
    elif args.uploadmenuimage:
        upload_menu_image_story()
    elif args.uploadweather:
        upload_weather_story()
    elif args.genweather:
        generate_weather_image()
    elif args.uploadnow:
        job_text_menu_weather()
    else:
        logger.info("Program initiated.")
        register_schedules()
        next_run = schedule.next_run()
        logger.info(f"Next scheduled run at: {next_run}")
        while True:
            schedule.run_pending()
            time.sleep(1)

if __name__ == "__main__":
    main()