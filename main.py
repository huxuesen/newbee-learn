import json
import logging
import os
import time

import requests

import config
import login
from course import CourseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

session = requests.Session()


def get_headers(token):
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36",
        "token": token,
        "authToken": token,
        "siteId": "95",
        "Content-Type": "application/json",
    }


def check_login(token):
    if not token:
        return False

    headers = get_headers(token)
    url = "https://www.baomi.org.cn/portal/main-api/checkToken.do"
    try:
        response = session.get(url, headers=headers).json()
        if response.get("result"):
            nickname = response["data"].get("nickName")
            return nickname or "未设定姓名"
    except Exception as e:
        logging.error(f"检查 token 失败: {e}")
    return False


def perform_login(loginName, passWord):
    token = login.login(loginName, passWord)
    print(f"登录成功，已获取 token")
    return loginName, passWord, token


def display_course_menu():
    print(f"\n============ 课程管理菜单 ============")
    print(f"1. 查看课程目录")
    print(f"2. 查看课程进度")
    print(f"3. 开始学习课程")
    print(f"4. 完成课程考试")
    print(f"0. 退出程序")
    return input(f"\n请选择操作 (0-4): ")


def handle_course_menu(course_manager, course_packet_id):
    while True:
        choice = display_course_menu()

        if choice == "0":
            print(f"\n感谢使用，再见！")
            break
        if choice == "1":
            course_info = course_manager.get_course_info(course_packet_id)
            if course_info and course_info.get("data"):
                print(f"\n当前课程: {course_info['data']['name']}")
                print(f"课程说明: {course_info['data']['note']}")

                directory = course_manager.get_course_directory(course_packet_id)
                if directory and directory.get("data"):
                    print(f"\n课程目录:")
                    for section in directory["data"]:
                        print(f"\n{section['name']}")
                        for sub in section["subDirectory"]:
                            print(f"  - {sub['name']}")
        elif choice == "2":
            progress = course_manager.get_course_progress(course_packet_id)
            if progress and progress.get("data"):
                data = progress["data"]
                print(f"\n课程进度信息:")
                print(f"课程名称: {data['courseName']}")
                print(f"学习进度: {data['progressRate'] * 100:.1f}%")
                print(f"已学课程数: {data['studyResourceNum']}/{data['resourceSum']}")
                print(f"总学习时长: {data['totalStudyTime']} 秒")
                print(f"是否完成: {'是' if data['isFinish'] else '否'}")
                print(f"是否获得证书: {'是' if data['isCertificate'] else '否'}")
        elif choice == "3":
            print(f"\n开始自动学习课程...")
            if course_manager.study_course(course_packet_id):
                print(f"\n课程学习完成！")
            else:
                print(f"\n课程学习失败，请稍后重试")
        elif choice == "4":
            print(f"\n开始自动完成考试...")
            if course_manager.complete_exam(course_packet_id):
                print(f"\n考试完成！")
            else:
                print(f"\n考试完成失败，请稍后重试")
        else:
            print(f"\n无效的选择，请重试")


if __name__ == "__main__":
    print(f"============ 保密教育登录程序 ============")
    loginName = input("请输入用户名: ")
    passWord = input("请输入密码: ")

    try:
        loginName, passWord, token = perform_login(loginName, passWord)
    except Exception as e:
        print(f"登录失败: {e}")
        exit(1)

    nickname = check_login(token)
    if nickname:
        print(f"登录成功! 欢迎, {nickname}")
        course_manager = CourseManager(session, token)
        handle_course_menu(course_manager, config.course_packet_id)
    else:
        print(f"登录失败或 token 无效")
