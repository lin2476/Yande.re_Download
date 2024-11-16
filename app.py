from flask import Flask, request, render_template, jsonify
import os
import threading
import logging
import webbrowser
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# 全局变量，用于跟踪正在进行的任务
tasks = {}
lock = threading.Lock()

def setup_webdriver():
    # 设置 Selenium WebDriver
    chromedriver_path = 'C:\\Users\\lin\\.wdm\\drivers\\chromedriver\\win64\\127.0.6533.88\\chromedriver-win32\\chromedriver.exe'
    service = Service(executable_path=chromedriver_path)
    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def load_images(driver, url):
    # 加载页面上的图片
    driver.get(url)
    wait = WebDriverWait(driver, 10)
    try:
        # 等待图片元素加载完成
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, '#post-list-posts .directlink.largeimg')))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
    except Exception as e:
        logging.error(f"Error waiting for images to load: {e}")
    time.sleep(3)
    return driver.page_source

def parse_html(page_source):
    # 解析页面源代码，提取图片 URL
    soup = BeautifulSoup(page_source, 'html.parser')
    image_elements = soup.select('#post-list-posts .directlink.largeimg')
    image_urls = [img['href'] for img in image_elements if img.get('href')]
    return image_urls

def download_image(url, folder):
    # 下载单个图片
    retries = 3
    headers = {'User-Agent': 'Mozilla/5.0'}  # 添加 User-Agent 头
    response = None
    while retries > 0:
        try:
            response = requests.get(url, stream=True, headers=headers, timeout=(10, 60))
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            logging.warning(f"Error downloading {url}, retries left: {retries-1}: {e}")
            retries -= 1
            time.sleep(2)
    if response and response.status_code == 200:
        filename = os.path.basename(url)
        save_path = os.path.join(folder, filename)
        with open(save_path, 'wb') as file:
            for chunk in response.iter_content(1024):
                file.write(chunk)
        logging.info(f"Downloaded: {filename}")
    else:
        logging.error(f"Failed to download {url}")

def download_images_concurrently(image_urls, folder, max_workers=10):
    # 并发下载图片
    os.makedirs(folder, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_image, url, folder): url for url in image_urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                future.result()
            except Exception as e:
                logging.error(f"Error downloading {url}: {e}")

def paginate_and_download(base_url, folder, start_page=1, end_page=5, task_id=None):
    # 分页下载图片
    driver = setup_webdriver()
    current_page = start_page
    try:
        while current_page <= end_page:
            url = f"{base_url}&page={current_page}"
            logging.info(f"Processing page {current_page}: {url}")
            page_source = load_images(driver, url)
            image_urls = parse_html(page_source)
            if image_urls:
                logging.info(f"Found {len(image_urls)} images on page {current_page}")
                download_images_concurrently(image_urls, folder, max_workers=10)
            else:
                logging.info(f"No images found on page {current_page}")
            if current_page < end_page:
                try:
                    # 查找并点击下一页按钮
                    next_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, '//a[@class="next_page"][contains(@aria-label, "Next page")]'))
                    )
                    next_button.click()
                except Exception as e:
                    logging.warning(f"No more pages or error navigating to the next page: {e}")
                    break
            time.sleep(3)
            current_page += 1
    finally:
        driver.quit()
        if task_id is not None:
            with lock:
                del tasks[task_id]

@app.route('/')
def index():
    # 主页路由，返回 HTML 页面
    return render_template('index.html')

@app.route('/start_download', methods=['POST'])
def start_download():
    # 开始下载任务的路由
    url = request.form['url']
    folder = request.form['folder']
    start_page = int(request.form.get('start_page', 1))
    end_page = int(request.form.get('end_page', 5))
    
    if not url or not folder:
        return jsonify({'status': 'error', 'message': 'URL and folder are required.'})
    
    # 在单独的线程中启动下载任务
    def task(task_id):
        paginate_and_download(url, folder, start_page, end_page, task_id)
    
    with lock:
        task_id = len(tasks) + 1
        tasks[task_id] = threading.Thread(target=task, args=(task_id,))
        tasks[task_id].start()
    
    return jsonify({'status': 'success', 'message': f'Download started with Task ID: {task_id}', 'task_id': task_id})

@app.route('/status', methods=['GET'])
def status():
    # 获取当前任务状态的路由
    return jsonify({'tasks': list(tasks.keys())})

if __name__ == '__main__':
    # 自动打开浏览器
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(debug=True)