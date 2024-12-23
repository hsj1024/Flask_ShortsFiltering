from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import requests
import time
import os
from concurrent.futures import ThreadPoolExecutor
import pymysql
import logging
import urllib.parse

app = Flask(__name__)

# YouTube Data API 키 설정
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# RDS 데이터베이스 정보
RDS_CONFIG = {
    "host": os.getenv("AI_DB_HOST"),
    "user": os.getenv("AI_DB_USER"),
    "password": os.getenv("AI_DB_PASSWORD"),
    "database": os.getenv("AI_DB_NAME"),
    "port": (int)(os.getenv("AI_DB_PORT")),
}


# 로깅 설정
logging.basicConfig(
    level=logging.DEBUG,  # 디버그 로그 레벨
    format="%(asctime)s - %(levelname)s - %(message)s",
)

def initialize_database():
    """RDS에서 shorts 테이블 자동 생성"""
    logging.info("initialize_database 함수 시작")
    retry_count = 5
    while retry_count > 0:
        conn = None
        try:
            # RDS 연결 설정
            logging.debug(f"RDS 연결 시도: {RDS_CONFIG}")
            conn = pymysql.connect(**RDS_CONFIG)
            cursor = conn.cursor()

            # shorts 테이블 생성
            create_table_query = """
            CREATE TABLE IF NOT EXISTS shorts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                product_code INT NOT NULL,
                shorts_id VARCHAR(255) NOT NULL,
                shorts_url TEXT NOT NULL,
                thumbnail_url TEXT NOT NULL,
                sentiment_score FLOAT NOT NULL,
                sentiment_label TEXT DEFAULT 'POSITIVE'
            );
            """
            cursor.execute(create_table_query)
            conn.commit()
            logging.info("Table 'shorts' has been created or already exists.")
            break

        except pymysql.Error as e:
            logging.error(f"Error initializing database: {e}")
            retry_count -= 1
            if retry_count == 0:
                raise Exception("DB 초기화 실패. DB가 준비되지 않았습니다.")
            time.sleep(5)  # 재시도 전 대기

        finally:
            if conn:
                conn.close()
                logging.debug("initialize_database 연결 종료")


# 앱 시작 시 데이터베이스 초기화
initialize_database()


# 한국어 감정 분석 함수 확장
def analyze_sentiment_korean(title):
    positive_words = [
        "좋아요",
        "훌륭",
        "추천",
        "최고",
        "멋져요",
        "기쁨",
        "재미있어요",
        "흥미",
        "활발",
        "신나요",
        "트렌디",
        "완벽",
        "필수템",
        "대박",
        "코디",
        "사랑해요",
        "만족",
        "고마워요",
        "행복",
        "짱",
        "뛰어나요",
        "감동",
        "깔끔해요",
        "예뻐요",
        "멋있어요",
        "흥미진진",
        "기대 이상",
        "강추",
        "유익해요",
        "화려해요",
        "만족스러워요",
        "최상급",
        "열정적",
        "센스있어요",
        "따뜻해요",
        "귀여워요",
        "유용해요",
        "효과적",
        "편리해요",
        "아름다워요",
        "착해요",
        "믿음직해요",
        "든든해요",
        "눈부셔요",
        "희망적",
        "최고예요",
        "성공적",
        "감사해요",
        "필요한 정보",
        "기대돼요",
        "명작",
        "혁신적",
        "세련됐어요",
        "대단해요",
        "행복해요",
        "잘했어요",
        "든든",
        "최고의 선택",
        "활기차요",
    ]
    negative_words = [
        "별로",
        "싫어요",
        "나빠요",
        "문제",
        "불만",
        "지루해요",
        "실망",
        "화나요",
        "사지 마세요",
        "짜증",
        "최악",
        "낡았어요",
        "불편해요",
        "구려요",
        "후회",
        "실패작",
        "거슬려요",
        "불쾌해요",
        "망했어요",
        "부족해요",
        "무의미",
        "고장났어요",
        "안좋아요",
        "별로예요",
        "비추",
        "돈낭비",
        "별로다",
        "쓸데없어요",
        "형편없어요",
        "불신",
        "망가졌어요",
        "촌스러워요",
        "하자 있어요",
        "어이없어요",
        "엉망이에요",
        "느려요",
        "부정적",
        "오류",
        "이해 안돼요",
        "낭비예요",
        "불성실",
        "도움 안돼요",
        "나쁘다",
        "아쉬워요",
        "쓸모없어요",
        "무리예요",
        "이상해요",
        "싫다",
        "후졌다",
        "최악이에요",
        "우울",
        "불쾌",
        "어려워요",
        "부실해요",
        "불합리해요",
        "답답해요",
        "이상하다",
        "애매해요",
    ]
    sentiment = 0
    for word in positive_words:
        if word in title:
            sentiment += 1
    for word in negative_words:
        if word in title:
            sentiment -= 1

    return sentiment


# 조회수와 좋아요 수를 추출하는 함수
def fetch_views_likes(video_element):
    try:
        views = video_element.find_element(
            By.XPATH, ".//span[contains(text(), '조회수')]"
        ).text
        likes = video_element.find_element(
            By.XPATH, ".//span[contains(text(), '좋아요')]"
        ).text

        # 조회수와 좋아요 수에서 숫자만 추출
        views = int(views.replace("조회수", "").replace(",", "").strip().split()[0])
        likes = int(likes.replace("좋아요", "").replace(",", "").strip().split()[0])
        return views, likes
    except Exception as e:
        print(f"Error extracting views/likes: {e}")
        return 0, 0


# 유튜브 메타데이터 가져오기
def fetch_video_metadata(video_id):
    """유튜브 메타데이터 가져오기"""
    url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={video_id}&key={YOUTUBE_API_KEY}"
    logging.debug(f"Fetching metadata for video ID: {video_id}")
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"Metadata response: {data}")
        if "items" in data and len(data["items"]) > 0:
            stats = data["items"][0]["statistics"]
            return {
                # "viewCount": int(stats.get("viewCount", 0)),
                "likeCount": int(stats.get("likeCount", 0)),
            }
        else:
            return {
                # "viewCount": 0,
                "likeCount": 0
            }

    except Exception as e:
        logging.error(f"Error fetching metadata for video {video_id}: {e}")
        return {
            # "viewCount": 0,
            "likeCount": 0
        }


def get_chrome_options():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # GUI 없이 실행 (필수)
    chrome_options.add_argument("--no-sandbox")  # Root 권한 문제 해결
    chrome_options.add_argument("--disable-dev-shm-usage")  # 공유 메모리 문제 해결
    chrome_options.add_argument(
        "--disable-gpu"
    )  # GPU 사용 비활성화 (헤드리스 모드에서 필요)
    chrome_options.add_argument("--remote-debugging-port=9222")  # 디버깅 포트 설정
    chrome_options.add_argument("--window-size=1920,1080")  # 브라우저 크기 설정
    chrome_options.add_argument("--disable-infobars")  # Chrome 자동화 메시지 비활성화
    chrome_options.add_argument("--disable-extensions")  # 확장 프로그램 비활성화
    chrome_options.add_argument("--start-maximized")  # 최대화된 상태로 실행
    return chrome_options


# ChromeDriver 설정 함수
def get_chrome_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # GUI 없이 실행
    chrome_options.add_argument("--no-sandbox")  # Root 권한 문제 해결
    chrome_options.add_argument("--disable-dev-shm-usage")  # 공유 메모리 문제 해결
    chrome_options.add_argument("--disable-gpu")  # GPU 사용 비활성화
    chrome_options.add_argument("--remote-debugging-port=9222")  # 디버깅 포트 설정
    chrome_options.add_argument("--window-size=1920,1080")  # 브라우저 크기 설정
    chrome_options.add_argument("--disable-infobars")  # Chrome 자동화 메시지 비활성화
    chrome_options.add_argument("--disable-extensions")  # 확장 프로그램 비활성화
    chrome_options.add_argument("--start-maximized")  # 최대화된 상태로 실행

    # Selenium Manager를 활용하여 WebDriver 설정
    return webdriver.Chrome(options=chrome_options)


# 병렬로 각 쇼츠의 썸네일 URL 가져오기
def generate_thumbnail_url(video_id):
    """YouTube video_id에서 썸네일 URL 생성"""
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def extract_video_id(url):
    """URL에서 YouTube video ID를 추출"""
    parsed_url = urllib.parse.urlparse(url)
    if "youtube.com" in parsed_url.netloc:
        if parsed_url.path.startswith("/watch"):
            query_params = urllib.parse.parse_qs(parsed_url.query)
            return query_params.get("v", [None])[0]  # 'v' 파라미터 값 추출
        elif parsed_url.path.startswith("/shorts"):
            return parsed_url.path.split("/")[-1]  # shorts/{video_id}에서 video_id 추출
    return None


# 유튜브 쇼츠 가져오기
def fetch_youtube_shorts(product_code, product_name, max_results=50, retries=3):
    """
    유튜브 Shorts 검색
    :param product_code: 상품 코드
    :param product_name: 상품 이름
    :param max_results: 최대 검색 결과 수
    :param retries: 재검색 시도 횟수
    :return: 검색된 Shorts 리스트
    """
    logging.debug(f"Fetching YouTube Shorts for product_name: {product_name}")
    driver = get_chrome_driver()
    shorts_videos = []

    try:
        # 유튜브 검색
        driver.get("https://www.youtube.com")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "search_query"))
        )
        search_box = driver.find_element(By.NAME, "search_query")
        search_box.send_keys(product_name + " shorts")  # 'shorts' 키워드 포함
        search_box.send_keys(Keys.RETURN)
        time.sleep(5)  # 검색 결과 로딩 대기

        # 스크롤 반복으로 더 많은 결과 확보
        for _ in range(3):  # 3번 스크롤
            driver.execute_script(
                "window.scrollTo(0, document.documentElement.scrollHeight);"
            )
            time.sleep(2)  # 스크롤 후 대기

        # 검색 결과 크롤링
        videos = driver.find_elements(By.XPATH, "//ytd-video-renderer")
        logging.debug(f"Found {len(videos)} videos.")
        if not videos:
            logging.warning("No videos found.")
            return []

        for video in videos[:max_results]:
            try:
                # URL 및 제목 추출
                shorts_url = video.find_element(
                    By.XPATH, ".//a[@id='thumbnail']"
                ).get_attribute("href")
                title_element = video.find_element(
                    By.XPATH,
                    ".//yt-formatted-string[@class='style-scope ytd-video-renderer']",
                )
                title = title_element.text
                shorts_id = extract_video_id(shorts_url)

                # Shorts만 필터링
                if not shorts_id or "shorts" not in shorts_url:
                    continue

                # 감정 분석 및 메타데이터 가져오기
                sentiment = analyze_sentiment_korean(title)
                metadata = fetch_video_metadata(shorts_id)

                video_data = {
                    "product_code": product_code,
                    "title": title,
                    "shorts_id": shorts_id,
                    "shorts_url": shorts_url,
                    "thumbnail_url": generate_thumbnail_url(shorts_id),
                    "sentiment": sentiment,
                    # "viewCount": metadata["viewCount"],
                    "likeCount": metadata["likeCount"],
                }
                shorts_videos.append(video_data)

            except Exception as e:
                logging.error(f"Error processing video: {e}")
                continue

        # 재검색 (부족한 경우)
        if len(shorts_videos) < 3 and retries > 0:
            logging.warning(f"Only {len(shorts_videos)} Shorts found. Retrying...")
            additional_videos = fetch_youtube_shorts(
                product_code, product_name, max_results, retries - 1
            )
            shorts_videos.extend(additional_videos)

        # 상위 3개 필터링 (좋아요 + 조회수 기준 정렬) x["viewCount"] +
        sorted_videos = sorted(
            shorts_videos, key=lambda x: x["likeCount"], reverse=True
        )[:3]
        return sorted_videos

    except Exception as e:
        logging.error(f"Error fetching YouTube Shorts: {e}")
        return []

    finally:
        driver.quit()


# 일반 영상 가져오기
def fetch_youtube_videos(product_code, product_name):
    logging.debug(f"Fetching YouTube videos for product_name: {product_name}")
    driver = get_chrome_driver()  # Selenium WebDriver 사용
    videos = []

    try:
        # 유튜브 검색
        driver.get("https://www.youtube.com")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "search_query"))
        )
        search_box = driver.find_element(By.NAME, "search_query")
        search_box.send_keys(product_name + " shorts")  # 'shorts' 키워드 포함하여 검색
        search_box.send_keys(Keys.RETURN)
        time.sleep(5)  # 검색 결과 로딩 대기

        # 동영상 리스트 가져오기
        logging.debug("Searching for videos...")
        video_elements = driver.find_elements(By.XPATH, "//ytd-video-renderer")
        logging.debug(f"Found {len(video_elements)} videos.")

        if not video_elements:
            logging.warning("No videos found.")
            return []

        for video in video_elements[:10]:  # 최대 10개의 동영상만 처리
            try:
                title_element = video.find_element(
                    By.XPATH,
                    ".//yt-formatted-string[@class='style-scope ytd-video-renderer']",
                )
                shorts_url = video.find_element(
                    By.XPATH, ".//a[@id='thumbnail']"
                ).get_attribute("href")
                shorts_id = extract_video_id(shorts_url)  # URL에서 정확히 video_id 추출
                title = title_element.text

                # 일반 영상 URL 필터링 (쇼츠 영상은 제외)
                if not shorts_id or shorts_url.startswith(
                    "https://www.youtube.com/shorts"
                ):
                    logging.warning(f"Skipping Shorts URL: {shorts_url}")
                    continue

                # 감정 분석 및 메타데이터 가져오기
                sentiment = analyze_sentiment_korean(title)
                metadata = fetch_video_metadata(shorts_id)

                video_data = {
                    "product_code": product_code,
                    "title": title,
                    "shorts_id": shorts_id,
                    "shorts_url": shorts_url,
                    "thumbnail_url": generate_thumbnail_url(
                        shorts_id
                    ),  # 썸네일 URL 직접 생성
                    "sentiment": sentiment,
                    # "viewCount": metadata["viewCount"],
                    "likeCount": metadata["likeCount"],
                }
                logging.debug(f"Video data fetched: {video_data}")
                videos.append(video_data)
            except Exception as e:
                logging.error(f"Error processing video: {e}")
                continue

        if not videos:
            logging.warning("No valid videos were processed.")
        else:
            logging.info(f"{len(videos)} videos fetched successfully.")

        # 상위 3개 비디오 선택 (조회수 + 좋아요 기반) x["viewCount"] +
        sorted_videos = sorted(videos, key=lambda x: x["likeCount"], reverse=True)
        return sorted_videos

    except Exception as e:
        logging.error(f"Error fetching YouTube videos: {e}")
        return []

    finally:
        driver.quit()


# 쇼츠 정보를 데이터베이스에 저장
def save_shorts_to_db(shorts_data):
    conn = None
    try:
        conn = pymysql.connect(**RDS_CONFIG)
        cursor = conn.cursor()

        for data in shorts_data:
            try:
                # 데이터베이스에 쇼츠 정보 삽입
                print(f"Saving to DB: {data}")  # 로그 추가
                insert_query = """
                INSERT INTO shorts (product_code, shorts_id, shorts_url, thumbnail_url, sentiment_score) 
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    shorts_id = VALUES(shorts_id),
                    shorts_url = VALUES(shorts_url), 
                    thumbnail_url = VALUES(thumbnail_url), 
                    sentiment_score = VALUES(sentiment_score);
                """
                cursor.execute(
                    insert_query,
                    (
                        data["product_code"],
                        data["shorts_id"],
                        data["shorts_url"],
                        data["thumbnail_url"],
                        data["sentiment"],
                    ),
                )
                conn.commit()
            except pymysql.Error as e:
                print(f"Error saving shorts data to database: {e}")
                conn.rollback()  # 에러 발생 시 롤백

    except pymysql.Error as e:
        print(f"Database connection error: {e}")
    finally:
        if conn:
            conn.close()


@app.route("/api/shorts/search", methods=["POST"])
def analyze_shorts():
    """API endpoint to analyze YouTube Shorts"""
    data = request.get_json()
    logging.debug(f"Received request data: {data}")
    if not data or "product_name" not in data or "product_code" not in data:
        logging.warning("Invalid input data")
        return (
            jsonify(
                {
                    "error": "Invalid input. 'product_code' and 'product_name' are required"
                }
            ),
            400,
        )

    product_code = data["product_code"]
    product_name = data["product_name"]

    # 테이블 확인 및 생성
    try:
        conn = pymysql.connect(**RDS_CONFIG)
        cursor = conn.cursor()

        create_table_query = """
        CREATE TABLE IF NOT EXISTS shorts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            product_code INT NOT NULL,
            shorts_id VARCHAR(255) NOT NULL,
            shorts_url TEXT NOT NULL,
            thumbnail_url TEXT NOT NULL,
            sentiment_score FLOAT NOT NULL
        );
        """
        cursor.execute(create_table_query)
        conn.commit()
        logging.info("Table verification completed.")
    except pymysql.Error as e:
        logging.error(f"Database error: {e}")
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()

    # 유튜브 쇼츠 데이터 가져오기
    try:
        logging.debug(f"Fetching YouTube Shorts for product: {product_name}")
        result = fetch_youtube_shorts(product_code, product_name)
        save_shorts_to_db(result)  # DB 저장 함수 호출
        logging.info("Shorts data fetched and saved successfully.")

        # add_on
        request_preprocess(product_code, result[0])

        return jsonify(result)
    except Exception as e:
        logging.error(f"Error fetching YouTube Shorts: {e}")
        return jsonify({"error": str(e)}), 500


# method_invoke
def request_preprocess(product_code, result):

    body = {
        "product_id": product_code,
        "shorts": {
            "youtube_url": result.get("shorts_url"),
            "youtube_thumbnail_url": result.get("thumbnail_url"),
            "shorts_id": result.get("shorts_id"),
        },
    }

    url = f"https://dotblossom.today/ai-api/metadata/product/shorts/{product_code}"

    headers = {"Content-type": "application/json"}

    try:
        response = requests.post(url, json=body, headers=headers, timeout=15)
        response.raise_for_status()
        print("데이터 전송 성공:", response.text)
    except requests.exceptions.RequestException as e:
        print("데이터 전송 실패:", e)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)