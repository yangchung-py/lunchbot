import os
import requests
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

# 기상청 API 키 및 좌표 설정
WEATHER_API_KEY = 'gBYKltlr75CUX2EsmTdfeKZDwv66kVEKfMIbPfHiW6%2F%2BvSopY97pj%2BFJ8yyWVSxofldcmz8tRjh2lIyqVhZx%2Bg%3D%3D'
NX = "58"  # 학교 좌표 X
NY = "126"  # 학교 좌표 Y

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

    path = "weather_test.jpg"
    img.save(path)
    print(f"이미지가 {path}에 저장되었습니다.")
    return path

if __name__ == "__main__":
    weather_data = get_weather_data()
    if weather_data:
        create_weather_image(weather_data)
    else:
        print("날씨 데이터를 가져오는 데 실패했습니다.")