import requests
import base64
import os

# 1. 基础配置（指向公司指南中的 128 服务器接口）
url = "http://192.168.210.108:8002/v1/chat/completions"
headers = {"Content-Type": "application/json"}

def encode_image_to_base64(image_path):
    """将本地图片读取并转换为 Base64 字符串"""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"找不到指定的图片文件: {image_path}")
        
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        
    # 根据图片后缀自动判断 MIME 类型（如 png 或 jpeg）
    ext = os.path.splitext(image_path)[1].lower().replace('.', '')
    if ext == 'jpg': ext = 'jpeg'
    
    # 拼接成 OpenAI 标准的 data URI 格式
    return f"data:image/{ext};base64,{encoded_string}"

def request_vlm():
    # 2. 准备你要让模型识别的本地图片路径
    # 比如你刚才保存在桌面上的图片，或者项目目录下的测试图
    image_file_path = "output.png" 
    
    try:
        print(f"正在读取并编码本地图片: {image_file_path} ...")
        image_base64_uri = encode_image_to_base64(image_file_path)
        # 3. 构造标准的 OpenAI 视觉请求参数体
        data = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        # 文本提示词
                        {
                            "type": "text", 
                            "text": "请详细描述一下这张图片里展示了什么内容，并帮我分析一下它的构图。"
                        },
                        # 图片内容（传入封装好的 Base64 URI）
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_base64_uri
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 1024,
            "temperature": 0.2  # 视觉分析任务建议调低推理温度，让描述更准确
        }
        
        # 4. 发送请求（视觉任务推理耗时较长，读取超时建议设置得大一些）
        print("正在向服务器发送 VLM 视觉推理请求...")
        response = requests.post(url, json=data, headers=headers, timeout=(5, 300))
        response.raise_for_status()
        
        # 5. 解析并输出结果
        result = response.json()
        reply = result["choices"][0]["message"]["content"]
        print("\n💡 Qwen-VL 视觉模型分析结果：")
        print(reply)
        
    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败！请检查云桌面有线网线是否插好，或 128 服务器服务是否启动。")
    except requests.exceptions.Timeout:
        print("❌ 请求超时！图片特征解析较慢或服务器显存吃紧。")
    except Exception as e:
        print(f"❌ 发生未知错误: {e}")

if __name__ == "__main__":
    request_vlm()