import time
import re
import itertools
import requests
import os
import random
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException


# ==================== 基础工具函数 ====================

def wait_for_element(driver, by, locator, timeout=15):
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, locator)))

def wait_for_elements(driver, by, locator, timeout=30):
    return WebDriverWait(driver, timeout).until(EC.presence_of_all_elements_located((by, locator)))

def is_modal_present(driver):
    """判断答题弹窗是否还在"""
    try:
        modal = driver.find_element(By.CSS_SELECTOR, '.ant-modal-body app-learning-video-question')
        return modal.is_displayed()
    except (NoSuchElementException, StaleElementReferenceException):
        return False


# ==================== AI 答题模块 ====================

def ask_ai_for_answer(question_title, options_texts, api_key, endpoint_id):
    """调用豆包 API 获取答案，返回选项索引列表 [0, 2]"""
    options_str = "\n".join([f"{chr(65+i)}. {text}" for i, text in enumerate(options_texts)])
    prompt = f"""
    你是一个专业的考试答题助手。请回答以下题目：
    题目：{question_title}
    选项：
    {options_str}
    要求：
    1. 如果是单选题，请只返回一个正确选项的字母。
    2. 如果是多选题，请返回所有正确选项的字母，用逗号隔开。
    3. 不要返回任何解释或多余的文字，只返回字母（例如：A 或 A,C）。
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": endpoint_id,  # 这里填 Endpoint ID
        "messages": [
            {"role": "system", "content": "你是一个严谨的答题助手。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    try:
        response = requests.post(
            "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
            headers=headers, json=data, timeout=15
        )
        result_text = response.json()['choices'][0]['message']['content'].strip()
        print(f"  🤖 豆包返回：{result_text}")
        letters = re.findall(r'[A-Z]', result_text.upper())
        indices = list(set([ord(letter) - ord('A') for letter in letters]))
        return sorted(indices)
    except Exception as e:
        print(f"  ⚠️ 豆包请求失败: {e}")
        return None


def handle_quiz_modal(driver, modal, ai_api_key, endpoint_id):
    """处理答题弹窗：先 AI 答题，失败则穷举兜底"""
    try:
        # 1. 获取题目类型和题干
        question_text = modal.find_element(By.XPATH, './/strong').text
        is_multiple_choice = '多选题' in question_text
        question_title = modal.find_element(By.XPATH, './/div[contains(@class, "d-flex")]//p').text.strip()

        # 2. 获取所有选项元素和文本
        options = modal.find_elements(By.XPATH, './/label[contains(@class, "ant-checkbox-wrapper") or contains(@class, "ant-radio-wrapper")]')
        if not options:
            return False

        options_texts = []
        for opt in options:
            try:
                opt_text = opt.find_element(By.XPATH, './/p').text.strip()
                options_texts.append(opt_text)
            except:
                options_texts.append("未知选项")

        print(f"  📖 题目：{question_title}")

        # 3. 优先请求 AI 获取答案
        print("  🧠 正在请求 AI 大模型...")
        correct_indices = ask_ai_for_answer(question_title, options_texts, ai_api_key, endpoint_id)

        if correct_indices:
            print(f"  ✅ AI 解析出的正确选项索引：{correct_indices}")
            # 先清空之前的勾选
            for opt in options:
                try:
                    checkbox = opt.find_element(By.XPATH, './/input')
                    if checkbox.is_selected():
                        driver.execute_script("arguments[0].click();", opt)
                        time.sleep(0.2)
                except:
                    pass

            # 勾选 AI 给出的答案
            for idx in correct_indices:
                if idx < len(options):
                    driver.execute_script("arguments[0].click();", options[idx])
                    time.sleep(0.3)

            time.sleep(1)
            submit_btn = modal.find_element(By.XPATH, './/button[.//span[contains(text(), "提交")]]')
            driver.execute_script("arguments[0].click();", submit_btn)
            print("  ✅ AI 答案已提交")
            time.sleep(2)

            if not is_modal_present(driver):
                print("  🎉 AI 答题成功，弹窗已关闭！")
                return True

        # 4. 兜底逻辑：穷举
        print("  ⚠️ AI 答题未能成功关闭弹窗，启动暴力穷举兜底机制...")

        max_attempts = 15
        for attempt in range(max_attempts):
            if not is_modal_present(driver):
                return True

            print(f"  🔄 兜底第 {attempt+1} 次尝试答题...")

            # 重新定位弹窗，防止失效
            try:
                modal = driver.find_element(By.CSS_SELECTOR, '.ant-modal-body app-learning-video-question')
                options = modal.find_elements(By.XPATH, './/label[contains(@class, "ant-checkbox-wrapper") or contains(@class, "ant-radio-wrapper")]')
            except:
                return True

            # 清空已勾选
            for opt in options:
                try:
                    checkbox = opt.find_element(By.XPATH, './/input')
                    if checkbox.is_selected():
                        driver.execute_script("arguments[0].click();", opt)
                        time.sleep(0.2)
                except:
                    pass

            # 选择新组合
            if is_multiple_choice:
                combos = []
                for r in range(1, len(options) + 1):
                    combos.extend(list(itertools.combinations(range(len(options)), r)))
                target_combo = combos[attempt % len(combos)]
                print(f"  📌 多选题，尝试组合：{target_combo}")
                for idx in target_combo:
                    driver.execute_script("arguments[0].click();", options[idx])
                    time.sleep(0.2)
            else:
                target_index = attempt % len(options)
                print(f"  📌 单选题，尝试选择第 {target_index + 1} 个选项")
                driver.execute_script("arguments[0].click();", options[target_index])

            time.sleep(1)
            try:
                submit_btn = modal.find_element(By.XPATH, './/button[.//span[contains(text(), "提交")]]')
                driver.execute_script("arguments[0].click();", submit_btn)
            except:
                pass
            print("  ✅ 已点击提交")
            time.sleep(2)

            # 检查是否答错
            try:
                error_msg = driver.find_element(By.XPATH, '//*[contains(text(), "没有答对") or contains(text(), "错误")]')
                if error_msg.is_displayed():
                    print(f"  ❌ 提示：{error_msg.text.strip()}，准备重试...")
                    continue
            except NoSuchElementException:
                pass

            if not is_modal_present(driver):
                print("  🎉 兜底答题成功，弹窗已关闭！")
                return True

        print("  ❌ 尝试了多次仍未答对，可能遇到死题，跳过...")
        return False

    except Exception as e:
        print(f"  ⚠️ 处理答题弹窗异常: {e}")
        return False


# ==================== 登录模块 ====================

def login_to_site(driver, username, password):
    wait_for_element(driver, By.XPATH, '//*[@id="app"]/div[1]/div[1]/div/div[2]/div/a').click()
    username_field = wait_for_element(driver, By.XPATH, '//*[@id="username"]')
    password_field = wait_for_element(driver, By.XPATH, '//*[@id="password"]')
    username_field.send_keys(username)
    password_field.send_keys(password)
    wait_for_element(driver, By.XPATH, '//*[@id="app"]/section/section/div[2]/div/form/button').click()
    time.sleep(5)


# ==================== 视频播放主逻辑 ====================

def video_play(driver, ai_api_key, endpoint_id):
    main_window = driver.current_window_handle

    driver.get('https://yxjc.qlteacher.com/project/yey2026/lesson/learn')
    time.sleep(3)

    # 关闭弹窗（如果有）
    try:
        wait_for_element(driver, By.XPATH, '//*[@id="dui_hua_kuang"]/div[1]/a[2]').click()
    except Exception:
        pass

    # 🚀 可选增强 1：极速跳过机制（如果全部学完，直接返回）
    try:
        unfinished = driver.find_elements(
            By.XPATH, 
            '//li[contains(@class,"ant-list-item")]//button[contains(@class,"hover-show")]//span[text()="开始学习"]'
        )
        if not unfinished:
            print("🎉 当前账号所有课程均已完成，无需学习，直接跳过！")
            return
    except Exception:
        pass

    # 获取所有大类按钮
    video_elements = wait_for_elements(driver, By.XPATH, '//button[@nztype="primary"]')

    for i in range(len(video_elements)):
        video_elements = wait_for_elements(driver, By.XPATH, '//button[@nztype="primary"]')
        if i >= len(video_elements):
            break

        current_btn = video_elements[i]
        try:
            i_text = current_btn.find_element(By.XPATH, './/span').text
        except Exception:
            continue

        course_title = "未知课程"
        try:
            row_element = current_btn.find_element(By.XPATH, './ancestor::div[contains(@class, "ant-row")][1]')
            title_element = row_element.find_element(By.XPATH, './/span[contains(@class, "ellipsis-title")]')
            course_title = title_element.get_attribute('title')
        except Exception:
            pass

        if i_text == '温故知新':
            print(f"  ⏭️ 跳过：温故知新 -> {course_title}")
            continue

        print(f"▶️ 进入“{course_title}”大模块: {i_text}")

        original_handles = driver.window_handles
        driver.execute_script("arguments[0].click();", current_btn)

        try:
            WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(len(original_handles) + 1))
        except TimeoutException:
            print("⚠️ 没有弹出新窗口，跳过")
            continue

        new_window = [h for h in driver.window_handles if h not in original_handles][0]
        driver.switch_to.window(new_window)
        time.sleep(5)

        # ==================== 处理新窗口里的课程列表 ====================
        processed_courses = set()

        while True:
            found_new = False

            try:
                li_elements = wait_for_elements(driver, By.XPATH, '//li[contains(@class, "ant-list-item")]')
            except TimeoutException:
                print("⚠️ 未找到课程列表")
                break

            for index in range(len(li_elements)):
                try:
                    li_elements = wait_for_elements(driver, By.XPATH, '//li[contains(@class, "ant-list-item")]')
                    if index >= len(li_elements):
                        break

                    current_li = li_elements[index]

                    # 抓取标题
                    title_elements = current_li.find_elements(By.XPATH, './/div[contains(@class, "ellipsis")]')
                    if not title_elements:
                        title_elements = current_li.find_elements(By.XPATH, './/ellipsis//div[1]')

                    if title_elements:
                        full_text = title_elements[0].text.strip()
                        course_title = full_text.replace("必学", "").strip()
                    else:
                        course_title = "未知课程"

                    # 找按钮
                    button_text = ""
                    btn = None
                    try:
                        btn = current_li.find_element(By.XPATH, './/button[contains(@class, "hover-show")]')
                        button_text = btn.find_element(By.XPATH, './/span').text.strip()
                    except NoSuchElementException:
                        pass

                    # 跳过逻辑
                    if course_title in processed_courses:
                        continue
                    if button_text == '复习一下':
                        print(f"  ⏭️ 跳过（已复习）：{course_title}")
                        processed_courses.add(course_title)
                        continue

                    is_completed = current_li.find_elements(By.XPATH, './/span[contains(@class, "text-999") and text()="已完成"]')
                    if is_completed and button_text != '开始学习':
                        print(f"  ⏭️ 跳过（已完成）：{course_title}")
                        processed_courses.add(course_title)
                        continue

                    # 点击学习
                    print(f"  ▶️ 准备学习：{course_title}")
                    if button_text == '开始学习' and btn is not None:
                        driver.execute_script("arguments[0].click();", btn)
                    else:
                        driver.execute_script("arguments[0].click();", current_li)

                    processed_courses.add(course_title)
                    found_new = True
                    time.sleep(3)
                    break

                except Exception as e:
                    print(f"  ⚠️ 处理第 {index+1} 个课程出错: {e}")
                    continue

            if not found_new:
                print("🎉 当前页面所有课程处理完毕")
                break

            # ==================== 视频监控逻辑 ====================
            video_element = None
            for _ in range(15):
                video_element = driver.execute_script("return document.querySelector('video');")
                if video_element is not None:
                    break
                time.sleep(1)

            if video_element is None:
                print("❌ 找不到视频元素，退出当前课程")
                driver.back()
                time.sleep(3)
                continue

            # 静音并尝试播放
            try:
                driver.execute_script("arguments[0].muted = true;", video_element)
            except:
                pass

            video_finished = False
            monitor_start = time.time()
            max_monitor_time = 3600 * 2

            while True:
                try:
                    if time.time() - monitor_start > max_monitor_time:
                        print("⚠️ 视频监控超时，强制退出")
                        break

                    time.sleep(3)

                    # 检查答题弹窗
                    if is_modal_present(driver):
                        print("📝 检测到答题弹窗！")
                        modal = driver.find_element(By.CSS_SELECTOR, '.ant-modal-body app-learning-video-question')
                        success = handle_quiz_modal(driver, modal, ai_api_key, endpoint_id)
                        if success:
                            print("  ✅ 弹窗处理完毕")
                        else:
                            print("  ❌ 弹窗处理失败")
                        time.sleep(2)
                        continue

                    # 重新获取 video_element
                    video_element = driver.execute_script("return document.querySelector('video');")
                    if video_element is None:
                        print("⚠️ 视频元素消失")
                        break

                    # 检查暂停
                    is_paused = driver.execute_script("return arguments[0].paused;", video_element)
                    if is_paused:
                        print("⏸️ 视频暂停，尝试恢复...")
                        try:
                            big_play_btn = driver.find_element(By.CSS_SELECTOR, '.vjs-big-play-button')
                            driver.execute_script("arguments[0].click();", big_play_btn)
                        except:
                            try:
                                control_play_btn = driver.find_element(By.CSS_SELECTOR, '.vjs-play-control')
                                driver.execute_script("arguments[0].click();", control_play_btn)
                            except:
                                pass
                        time.sleep(2)

                    # 检查完成状态
                    try:
                        count_down = driver.find_element(By.XPATH, '//div[contains(@class, "count-down")]')
                        status = count_down.text.strip()
                        print(f"  🕒 状态: {status if status else '播放中...'}")
                        if status == '已完成':
                            print("  🎉 视频播放完毕！")
                            video_finished = True
                            break
                    except NoSuchElementException:
                        time.sleep(2)

                except Exception as e:
                    print(f"  ⚠️ 视频监控异常: {e}")
                    break

            # 返回列表
            try:
                driver.back()
                time.sleep(3)
            except:
                pass
            video_element = None

        # 当前模块处理完，关闭新窗口
        try:
            driver.close()
        except:
            pass
        driver.switch_to.window(main_window)
        time.sleep(3)


# ==================== 浏览器驱动 ====================

def create_driver():
    from selenium import webdriver

    print("🚀 程序开始运行，准备启动浏览器...")

    options = webdriver.ChromeOptions()
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,900")
    options.add_argument("--log-level=3")

    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=options)

    stealth_js = """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) { return 'Intel Inc.'; }
            if (parameter === 37446) { return 'Intel Iris OpenGL Engine'; }
            return originalGetParameter.apply(this, arguments);
        };
    """
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js})
    driver.execute_cdp_cmd("Network.enable", {})

    return driver


# ==================== 环境清理（切换账号用） ====================

def cleanup_driver(driver):
    """切换账号前的环境清理：关闭子窗口、清 Cookie、回到主页"""
    try:
        current_handles = driver.window_handles
        if len(current_handles) > 1:
            main_handle = current_handles[0]
            for handle in current_handles[1:]:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                except Exception:
                    pass
            driver.switch_to.window(main_handle)
    except Exception as e:
        print(f"  ⚠️ 窗口清理异常: {e}")

    try:
        driver.delete_all_cookies()
        print("  🧹 已清除 Cookie")
    except Exception as e:
        print(f"  ⚠️ Cookie 清理异常: {e}")

    try:
        driver.get("https://www.qlteacher.com/")
        time.sleep(3)
    except Exception as e:
        print(f"  ⚠️ 页面刷新异常: {e}")


# ==================== 主程序入口（多账号控制） ====================

def main():
    # ==================== 配置多个账号 ====================
    accounts = [
        {"username": "450330199103071020", "password": "mq307305"},
        # {"username": "第二个账号", "password": "第二个密码"},
        # {"username": "第三个账号", "password": "第三个密码"},
    ]

    # ==================== 配置 AI 答题 ====================
    ai_api_key = "你的豆包API_Key"
    endpoint_id = "你的Endpoint_ID"

    print(f"🚀 共 {len(accounts)} 个账号待处理，准备启动浏览器...")
    driver = create_driver()

    for idx, acc in enumerate(accounts):
        print(f"\n{'=' * 50}")
        print(f"👉 开始处理第 {idx + 1}/{len(accounts)} 个账号: {acc['username']}")
        print(f"{'=' * 50}")

        try:
            # 1. 切换到该账号前，先清理环境
            cleanup_driver(driver)

            # 2. 登录
            print(f"🔐 正在登录: {acc['username']}")
            login_to_site(driver, acc['username'], acc['password'])

            # 3. 开始刷课
            print(f"🎬 账号 {acc['username']} 开始播放视频...")
            video_play(driver, ai_api_key, endpoint_id)

            print(f"✅ 账号 {acc['username']} 处理完毕！")

        except Exception as e:
            # 单个账号出错，打印日志，不影响下一个账号
            print(f"❌ 账号 {acc['username']} 处理失败: {type(e).__name__}: {e}")
            continue
        
        # 🚀 可选增强 2：账号切换之间的随机等待（3~8秒），防止触发风控
        if idx < len(accounts) - 1:
            wait_time = random.uniform(3, 8)
            print(f"⏳ 等待 {wait_time:.1f} 秒后切换下一个账号...")
            time.sleep(wait_time)

    print(f"\n{'=' * 50}")
    print("🎉 所有账号处理完毕，准备关闭浏览器...")
    print(f"{'=' * 50}")
    driver.quit()


if __name__ == "__main__":
    main()