import base64
import logging

import requests
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


def rsa_encrypt_pkcs1v15(data: str, public_key: str) -> str:
    """RSA 加密（PKCS#1 v1.5），公钥支持 PEM 或纯 Base64 格式。"""
    if not public_key.strip().startswith("-----BEGIN"):
        public_key = f"""-----BEGIN PUBLIC KEY-----
{public_key.strip()}
-----END PUBLIC KEY-----"""

    try:
        key = RSA.import_key(public_key)
        cipher = PKCS1_v1_5.new(key)
        encrypted_bytes = cipher.encrypt(data.encode())
        return base64.b64encode(encrypted_bytes).decode()
    except (ValueError, IndexError, TypeError) as e:
        raise ValueError("无效的公钥格式") from e


def encrypt(data):
    try:
        key_url = "https://www.baomi.org.cn/portal/main-api/getPublishKey.do"
        response = requests.get(key_url)
        if response.status_code != 200:
            logging.error(f"获取公钥失败，状态码: {response.status_code}")
            return None

        public_key = response.json()["data"]
        return rsa_encrypt_pkcs1v15(data, public_key)
    except Exception as e:
        logging.error(f"加密过程出错: {e}")
        raise Exception(f"加密数据失败: {e}") from e


def login(loginName, passWord):
    try:
        login_url = "https://www.baomi.org.cn/portal/main-api/loginInNew.do"
        payload = {
            "loginName": encrypt(loginName),
            "passWord": encrypt(passWord),
            "deviceId": 1711,
            "deviceOs": "pc",
            "lon": 40,
            "lat": 30,
            "siteId": "95",
            "sinopec": "false",
        }

        headers = {
            "Content-Type": "application/json",
            "siteId": "95",
        }
        response = requests.post(login_url, json=payload, headers=headers)
        if response.status_code != 200:
            logging.error(f"登录请求失败，状态码: {response.status_code}")
            raise Exception(f"登录请求失败，状态码: {response.status_code}")

        response_data = response.json()
        if not response_data.get("token"):
            error_msg = response_data.get("message", "未知错误")
            # 尝试从 error 字段获取更详细的错误信息
            if not error_msg or error_msg == "未知错误":
                err_info = response_data.get("error")
                if isinstance(err_info, dict):
                    error_msg = err_info.get("errorMsg", error_msg)
            logging.error(f"登录失败: {error_msg}")
            raise Exception(f"登录失败: {error_msg}")

        return response_data["token"]
    except Exception as e:
        logging.error(f"登录过程出错: {e}")
        raise
