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
from collections import Counter

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

        # API 요청 URL (시간 형식은 항상 4자리 문자열이어야 함 - 예: "0630")
        url = f'http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst?serviceKey={WEATHER_API_KEY}&pageNo=1&numOfRows=1000&dataType=JSON&base_date={base_date}&base_time=0630&nx={NX}&ny={NY}'
        
        print(f"요청 URL: {url}")  # 디버깅 정보
        
        response = requests.get(url)
        response.raise_for_status()
        
        # 응답 내용 확인 (디버깅용)
        print(f"응답 상태 코드: {response.status_code}")
        print(f"응답 헤더: {response.headers['Content-Type']}")
        
        try:
            data = response.json()
        except Exception as e:
            print(f"JSON 변환 오류: {e}")
            print(f"응답 내용: {response.text[:200]}...")  # 앞부분만 출력
            raise
        
        # 응답 구조 확인
        if 'response' not in data:
            print(f"예상치 못한 응답 형식: {data.keys()}")
            raise ValueError("API 응답에 'response' 키가 없습니다")
            
        if 'body' not in data['response']:
            print(f"예상치 못한 응답 형식: {data['response'].keys()}")
            raise ValueError("API 응답에 'body' 키가 없습니다")
            
        if 'items' not in data['response']['body']:
            print(f"예상치 못한 응답 형식: {data['response']['body'].keys()}")
            raise ValueError("API 응답에 'items' 키가 없습니다")
        
        if 'item' not in data['response']['body']['items']:
            print(f"예상치 못한 응답 형식: {data['response']['body']['items'].keys()}")
            raise ValueError("API 응답에 'item' 키가 없습니다")
        
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
        temps = []
        humidities = []
        precip_times = []
        precip_sum = 0.0
        sky_codes = []  # 하늘 상태 코드 저장
        precip_types_list = []  # 강수 형태 저장

        for time_str in sorted(forecasts.keys()):
            data = forecasts[time_str]
            
            # 온도
            if 'T1H' in data:
                try:
                    temp = float(data['T1H'])
                    temps.append(temp)
                except: 
                    pass

            # 습도
            if 'REH' in data:
                try:
                    humidity = float(data['REH'])
                    humidities.append(humidity)
                except:
                    pass

            # 하늘 상태
            if 'SKY' in data:
                try:
                    sky_codes.append(data['SKY'])
                except:
                    pass

            # 강수 형태 확인
            pty = data.get('PTY', '0')
            if pty != '0':
                # 강수형태(PTY) 코드 매핑
                precip_type_map = {
                    '0': '없음',
                    '1': '비',
                    '2': '비/눈',
                    '3': '눈',
                    '4': '소나기',
                    '5': '빗방울',
                    '6': '빗방울눈날림',
                    '7': '눈날림'
                }
                precip_type = precip_type_map.get(pty, f'알 수 없음({pty})')
                precip_types_list.append(precip_type)

            # 강수량 확인
            rn1 = data.get('RN1', '0')
            if rn1 not in ['0', '강수없음']:
                try:
                    # 강수량 문자열 파싱
                    if rn1 == '1mm 미만':
                        precip_sum += 0.5  # 1mm 미만은 0.5로 가정
                    elif 'mm' in rn1:
                        # 숫자 부분만 추출 (예: "2.0mm" -> 2.0)
                        precip_value = float(re.search(r'(\d+\.?\d*)', rn1).group(1))
                        precip_sum += precip_value
                    else:
                        try:
                            precip_sum += float(rn1)
                        except:
                            pass
                except Exception as e:
                    print(f"강수량 파싱 오류: {e} - 값: {rn1}")
                    pass

            # 강수 시간대 추가
            if pty != '0' or rn1 not in ['0', '강수없음']:
                precip_times.append(f"{time_str[:2]}:{time_str[2:]}")

        # 강수 시간대 그룹화
        time_ranges = []
        if precip_times:
            sorted_times = sorted(precip_times)
            current_start = current_end = sorted_times[0]
            for t in sorted_times[1:]:
                if int(t.replace(':', '')) - int(current_end.replace(':', '')) == 100:
                    current_end = t
                else:
                    if current_start == current_end:
                        time_ranges.append(current_start)  # 단일 시간대
                    else:
                        time_ranges.append(f"{current_start}~{current_end}")  # 연속 시간대
                    current_start = current_end = t
            if current_start == current_end:
                time_ranges.append(current_start)  # 마지막 단일 시간대
            else:
                time_ranges.append(f"{current_start}~{current_end}")  # 마지막 연속 시간대

        # 하늘 상태 결정 (가장 많이 나온 코드)
        sky_condition = "정보 없음"
        if sky_codes:
            # 하늘상태(SKY) 코드 : 맑음(1), 구름많음(3), 흐림(4)
            sky_map = {'1': '맑음', '3': '구름많음', '4': '흐림'}
            sky_counter = Counter(sky_codes)
            most_common_sky_code = sky_counter.most_common(1)[0][0]
            sky_condition = sky_map.get(most_common_sky_code, '알 수 없음')

        # 가장 많이 나온 강수 형태 결정
        precip_type = ""
        if precip_types_list:
            precip_counter = Counter(precip_types_list)
            most_common_precip = precip_counter.most_common(1)[0][0]
            precip_type = f", {most_common_precip}"

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
        import traceback
        print(f"Weather error: {e}")
        print(traceback.format_exc())
        return None

def create_weather_image(weather, output_path=None):
    img = Image.new('RGB', (1080, 1920), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    try:
        # 폰트 로드
        title_font = ImageFont.truetype("font.ttf", 60)
        label_font = ImageFont.truetype("font.ttf", 50)
        value_font = ImageFont.truetype("font.ttf", 48)
        source_font = ImageFont.truetype("font.ttf", 38)
    except:
        title_font = ImageFont.load_default()
        label_font = ImageFont.load_default()
        value_font = ImageFont.load_default()
        source_font = ImageFont.load_default()

    # 제목
    title = f"{weather['date']} 날씨"
    title_bbox = draw.textbbox((0,0), title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((1080-title_width)/2, 350), title, (0,0,0), font=title_font)

    # 출처
    source = "출처: 기상청 초단기예보"
    source_bbox = draw.textbbox((0,0), source, font=source_font)
    source_width = source_bbox[2] - source_bbox[0]
    draw.text(((1080-source_width)/2, 430), source, (100,100,100), font=source_font)

    # 날씨 정보 항목
    items = [
        {"label": "하늘 상태", "value": weather['weather_status']},
        {"label": "평균 온도", "value": f"{weather['avg_temp']:.1f}℃" if weather['avg_temp'] else "정보없음"},
        {"label": "평균 습도", "value": f"{weather['avg_humidity']:.1f}%" if weather['avg_humidity'] else "정보없음"},
        {"label": "강수 시간대", "value": ", ".join(weather['precip_times']) if weather['precip_times'] else "X"},
        {"label": "강수량", "value": f"{weather['precip_sum']:.1f}mm" if weather['precip_sum'] > 0 else "X"}
    ]
    
    # 시작 위치 설정
    current_y = 700
    line_spacing = 100  # 줄 간격
    center_x = 1080 // 2  # 중앙 X 좌표
    
    for item in items:
        # 레이블과 값을 한 줄에 표시
        text = f"{item['label']}: {item['value']}"
        
        # 줄바꿈이 필요한지 확인
        text_bbox = draw.textbbox((0, 0), text, font=label_font)
        text_width = text_bbox[2] - text_bbox[0]
        
        if text_width > 900:  # 너무 길면 레이블과 값을 두 줄로 나눔
            # 레이블 출력
            label_bbox = draw.textbbox((0, 0), item['label'] + ":", font=label_font)
            label_width = label_bbox[2] - label_bbox[0]
            draw.text(((1080-label_width)/2, current_y), item['label'] + ":", (0, 0, 0), font=label_font)
            
            # 값은 다음 줄에 출력
            current_y += 70
            value_bbox = draw.textbbox((0, 0), item['value'], font=value_font)
            value_width = value_bbox[2] - value_bbox[0]
            
            # 값이 너무 길면 잘라서 여러 줄로 출력
            if value_width > 900:
                words = item['value'].split()
                lines = []
                current_line = []
                
                for word in words:
                    test_line = current_line + [word]
                    test_text = " ".join(test_line)
                    test_bbox = draw.textbbox((0, 0), test_text, font=value_font)
                    test_width = test_bbox[2] - test_bbox[0]
                    
                    if test_width <= 900:
                        current_line = test_line
                    else:
                        if current_line:
                            lines.append(" ".join(current_line))
                        current_line = [word]
                
                if current_line:
                    lines.append(" ".join(current_line))
                
                # 각 줄 출력
                for line in lines:
                    line_bbox = draw.textbbox((0, 0), line, font=value_font)
                    line_width = line_bbox[2] - line_bbox[0]
                    draw.text(((1080-line_width)/2, current_y), line, (0, 0, 0), font=value_font)
                    current_y += 60
            else:
                # 한 줄로 충분한 경우
                draw.text(((1080-value_width)/2, current_y), item['value'], (0, 0, 0), font=value_font)
                current_y += line_spacing
        else:
            # 한 줄로 표시 가능한 경우
            draw.text(((1080-text_width)/2, current_y), text, (0, 0, 0), font=label_font)
            current_y += line_spacing
    
    if output_path:
        path = output_path
    else:
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

def generate_weather_image():
    weather_data = get_weather_data()
    if weather_data:
        return create_weather_image(weather_data, "./weather.png")
    return None

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
    parser.add_argument("--genweather", action="store_true", help="Generate weather image only")
    args = parser.parse_args()

    if args.genweather:
        generate_weather_image()
    elif args.uploadnow:
        fetch_and_upload_menu()
    else:
        print("Program initiated.")
        
        next_run = schedule.next_run()
        print(f"Next scheduled run at: {next_run}")

        while True:
            schedule.run_pending()
            time.sleep(1)