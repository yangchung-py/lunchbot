import os
import requests
import argparse
import schedule
import time
import re
from datetime import datetime, timedelta
from instagrapi import Client
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

# 환경 변수에서 값 불러오기
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
NX = os.getenv("NX")  # 학교 좌표 X
NY = os.getenv("NY")  # 학교 좌표 Y

IG_CREDENTIAL_PATH = "./ig_settings.json"
IG_IMAGE_PATH = "./menu"

class Bot:
    def __init__(self):
        self._cl = Client()
        if os.path.exists(IG_CREDENTIAL_PATH):
            self._cl.load_settings(IG_CREDENTIAL_PATH)
        self._cl.login(IG_USERNAME, IG_PASSWORD)
        self._cl.dump_settings(IG_CREDENTIAL_PATH)

    def upload_story(self, image_path):
        print("Uploading story...")
        self._cl.photo_upload_to_story(image_path)
        print("Story uploaded successfully.")

def get_weather_data():
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

        url = f'http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst?serviceKey={WEATHER_API_KEY}&pageNo=1&numOfRows=1000&dataType=JSON&base_date={base_date}&base_time=0630&nx={NX}&ny={NY}'
        
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        items = data['response']['body']['items']['item']
        today = now.strftime("%Y%m%d")

        forecasts = {}
        for item in items:
            if item['fcstDate'] != today:
                continue
            
            fcst_time = item['fcstTime']
            category = item['category']
            value = item['fcstValue']
            
            if fcst_time not in forecasts:
                forecasts[fcst_time] = {}
            forecasts[fcst_time][category] = value

        # 데이터 분석
        am_temps, pm_temps = [], []
        precip_times = []
        precip_sum = 0.0
        
        for time_str in sorted(forecasts.keys()):
            data = forecasts[time_str]
            hour = int(time_str[:2])
            
            # 온도
            if 'T1H' in data:
                try:
                    temp = float(data['T1H'])
                    if hour < 12: am_temps.append(temp)
                    else: pm_temps.append(temp)
                except: pass

            # 강수
            precip = False
            if data.get('PTY','0') != '0':
                precip = True
            if data.get('RN1','강수없음') not in ['0','강수없음']:
                precip = True
                try: precip_sum += float(data['RN1'])
                except: pass

            if precip:
                precip_times.append(f"{time_str[:2]}:{time_str[2:]}")

        # 강수 시간대 그룹화
        time_ranges = []
        if precip_times:
            sorted_times = sorted(precip_times)
            current_start = current_end = sorted_times[0]
            for t in sorted_times[1:]:
                if int(t.replace(':','')) - int(current_end.replace(':','')) == 100:
                    current_end = t
                else:
                    time_ranges.append(f"{current_start}~{current_end}")
                    current_start = current_end = t
            time_ranges.append(f"{current_start}~{current_end}")

        return {
            'date': now.strftime("%m월 %d일"),
            'am_temp': sum(am_temps)/len(am_temps) if am_temps else None,
            'pm_temp': sum(pm_temps)/len(pm_temps) if pm_temps else None,
            'precip': 'O' if precip_times else 'X',
            'precip_times': time_ranges,
            'precip_sum': precip_sum
        }

    except Exception as e:
        print(f"Weather error: {e}")
        return None

def create_weather_image(weather):
    img = Image.new('RGB', (1080, 1920), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("font.ttf", 60)
        small_font = ImageFont.truetype("font.ttf", 40)
    except:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # 제목
    title = f"{weather['date']} 날씨"
    w, h = draw.textbbox((0,0), title, font=font)[2:]
    draw.text(((1080-w)/2, 400), title, (0,0,0), font=font)

    # 출처
    source = "출처: 기상청 초단기예보"
    w, h = draw.textbbox((0,0), source, font=small_font)[2:]
    draw.text(((1080-w)/2, 500), source, (100,100,100), font=small_font)

    # 내용
    y = 700
    lines = [
        f"오전 평균 온도: {weather['am_temp']:.1f}℃" if weather['am_temp'] else "오전 온도: 정보없음",
        f"오후 평균 온도: {weather['pm_temp']:.1f}℃" if weather['pm_temp'] else "오후 온도: 정보없음",
        f"강수 여부: {weather['precip']}",
        "강수 시간대: " + (", ".join(weather['precip_times']) if weather['precip_times'] else "없음"),
        f"강수량: {weather['precip_sum']:.1f}mm"
    ]

    for line in lines:
        w, h = draw.textbbox((0,0), line, font=font)[2:]
        draw.text(((1080-w)/2, y), line, (0,0,0), font=font)
        y += h + 50

    path = f"{IG_IMAGE_PATH}/{datetime.now().strftime('%Y%m%d')}_weather.jpg"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print(f"Weather image created: {path}")
    return path

def fetch_and_upload_menu():
    bot = Bot()
    
    # 중식 메뉴 처리
    lunch_menu = get_meal_menu(2)
    if lunch_menu is not None:
        lunch_image_path = create_menu_image(lunch_menu, "중식", "_lunch")
        upload_story(bot, lunch_image_path)
        time.sleep(10)
        
        # 날씨 정보 처리 (점심 메뉴가 있을 때만)
        weather_data = get_weather_data()
        if weather_data:
            weather_image = create_weather_image(weather_data)
            upload_story(bot, weather_image)
    
    # 석식 메뉴 처리
    dinner_menu = get_meal_menu(3)
    if dinner_menu is not None:
        dinner_image_path = create_menu_image(dinner_menu, "석식", "_dinner")
        upload_story(bot, dinner_image_path)

def get_meal_menu(meal_code):
    today = datetime.now().strftime('%Y%m%d')
    url = f'https://open.neis.go.kr/hub/mealServiceDietInfo?Type=json&pSize=100&ATPT_OFCDC_SC_CODE=B10&SD_SCHUL_CODE=7010208&MMEAL_SC_CODE={meal_code}&MLSV_YMD={today}'
    
    try:
        print(f"Fetching {'lunch' if meal_code == 2 else 'dinner'} menu...")
        response = requests.get(url)
        response.raise_for_status()

        data = response.json()

        if 'mealServiceDietInfo' in data:
            menu_items = data['mealServiceDietInfo'][1]['row'][0]['DDISH_NM'].split('<br/>')
            # 괄호와 그 안의 내용 제거
            cleaned_menu = [re.sub(r'\s*\([^)]*\)', '', item.replace('y', '').strip()) for item in menu_items]
            menu = '\n'.join(cleaned_menu)
            print(f"{'Lunch' if meal_code == 2 else 'Dinner'} menu fetched successfully.")
        else:
            menu = None
            print(f"{'Lunch' if meal_code == 2 else 'Dinner'} menu not found.")
    except Exception as e:
        menu = None
        print(f"Error fetching meal menu: {e}")

    return menu

def create_menu_image(menu_text, meal_type, suffix):
    if menu_text is None:
        return None

    image_width = 1080
    image_height = 1920
    background_color = (255, 255, 255)
    text_color = (0, 0, 0)
    font_size = 60

    image = Image.new('RGB', (image_width, image_height), background_color)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("font.ttf", font_size)

    # 메뉴 타입과 메뉴 내용을 합침
    full_text = f"{meal_type}\n\n{menu_text}"
    
    text_bbox = draw.textbbox((0, 0), full_text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (image_width - text_width) / 2
    y = (image_height - text_height) / 2

    draw.text((x, y), full_text, fill=text_color, font=font)

    today = datetime.now().strftime('%Y%m%d')
    image_path = f'{IG_IMAGE_PATH}/{today}{suffix}.jpg'
    os.makedirs(os.path.dirname(image_path), exist_ok=True)
    image.save(image_path)
    print(f"Menu image created: {image_path}")
    return image_path

def upload_story(bot, image_path):
    if image_path is not None:
        bot.upload_story(image_path)

def job():
    fetch_and_upload_menu()

schedule.every().monday.at("07:00").do(job)
schedule.every().tuesday.at("07:00").do(job)
schedule.every().wednesday.at("07:00").do(job)
schedule.every().thursday.at("07:00").do(job)
schedule.every().friday.at("07:00").do(job)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload Instagram story")
    parser.add_argument("--uploadnow", action="store_true", help="Upload the story immediately")
    args = parser.parse_args()

    bot = Bot()
    #initiated_image_path = create_initiated_image()
    #bot.upload_story(initiated_image_path)
    #print("Initiated image uploaded successfully.")

    if args.uploadnow:
        fetch_and_upload_menu()
    else:
        print("Program initiated.")
        
        next_run = schedule.next_run()
        print(f"Next scheduled run at: {next_run}")

        while True:
            schedule.run_pending()
            time.sleep(1)